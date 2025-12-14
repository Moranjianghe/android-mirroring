import random
import string
import subprocess
import sys
import time
from zeroconf import Zeroconf, ServiceBrowser
import qrcode
import socket
import argparse

# 生成隨機 serviceId 和 password
def random_string(length=8):
    chars = string.ascii_letters + string.digits + '$'
    return ''.join(random.choice(chars) for _ in range(length))

# 顯示二維碼到終端
def print_qr(data):
    qr = qrcode.QRCode(border=1)
    qr.add_data(data)
    qr.make(fit=True)
    qr.print_ascii(invert=True)

# adb mdns check
def adb_mdns_check():
    try:
        result = subprocess.run(['adb', 'mdns', 'check'], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            print(result.stdout)
    except Exception as e:
        print(f'adb mdns check 執行失敗: {e}')


class ConnectListener:
    def __init__(self, ports=None):
        self.connected = False
        self.ip = None
        self.port = None
        self.ports = ports or []

    def remove_service(self, zeroconf, type, name):
        pass

    def update_service(self, zeroconf, type, name):
        pass

    def update_service(self, zeroconf, type, name):
        pass


    def add_service(self, zeroconf, type, name):
        print(f"[LOG] mDNS 發現服務(嘗試連線): {name}")
        info = zeroconf.get_service_info(type, name)
        if not info:
            return
        # 解析所有地址嘗試連線
        for addr_bytes in info.addresses:
            ip = '.'.join(str(b) for b in addr_bytes)
            advertised_port = info.port
            # 建立嘗試的埠順序：廣告埠先，接著使用者設定的埠
            try_ports = [advertised_port] + [p for p in self.ports if p != advertised_port]
            print(f"[LOG] 嘗試用 adb connect {ip} 的埠: {try_ports}")
            for try_port in try_ports:
                try:
                    result = subprocess.run([ADB_PATH, 'connect', f'{ip}:{try_port}'], capture_output=True, text=True, timeout=10)
                    out = (result.stdout or '') + (result.stderr or '')
                    print(f"[LOG] adb connect returncode: {result.returncode}")
                    print(f"[LOG] adb connect output: {out.strip()}")
                    if result.returncode == 0 or 'connected to' in out.lower():
                        print(f"已連線至 {ip}:{try_port}")
                        self.connected = True
                        self.ip = ip
                        self.port = try_port
                        return
                except Exception as e:
                    print(f"[LOG] adb connect 嘗試失敗: {e}")

class ConnectPortFinder:
    def __init__(self, target_ip):
        self.target_ip = target_ip
        self.port = None
        self.found = False

    def remove_service(self, zeroconf, type, name):
        pass

    def update_service(self, zeroconf, type, name):
        pass

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        if info:
            for addr_bytes in info.addresses:
                ip = '.'.join(str(b) for b in addr_bytes)
                if ip == self.target_ip:
                    self.port = info.port
                    self.found = True
                    return

def find_connect_port(target_ip, timeout=10):
    zeroconf = Zeroconf()
    listener = ConnectPortFinder(target_ip)
    browser = ServiceBrowser(zeroconf, '_adb-tls-connect._tcp.local.', listener)
    try:
        for _ in range(timeout):
            if listener.found:
                return listener.port
            time.sleep(1)
        return None
    finally:
        zeroconf.close()

# mDNS 服務發現
class AdbPairListener:
    def __init__(self, service_id, password, connect_ports=None):
        self.service_id = service_id
        self.password = password
        self.found = False
        self.connect_ports = connect_ports or [5555]

    def remove_service(self, zeroconf, type, name):
        pass

    def add_service(self, zeroconf, type, name):
        print(f"[LOG] mDNS 發現服務: {name}")
        info = zeroconf.get_service_info(type, name)
        if info:
            print(f"[LOG] 服務 info: name={info.name}, addresses={info.addresses}, port={info.port}")
        # 修正比對條件，僅比對主機名部分
        if info and info.name.split('.')[0] == self.service_id:
            ip = '.'.join(str(b) for b in info.addresses[0])
            port = info.port
            print(f"\n找到設備: {ip}:{port}\n開始配對...")
            self.found = True
            self.pair_device(ip, port)

    def pair_device(self, ip, port):
        print(f"[LOG] 嘗試 adb pair {ip}:{port} {self.password}")
        try:
            result = subprocess.run([
                ADB_PATH, 'pair', f'{ip}:{port}', self.password
            ], capture_output=True, text=True, timeout=20)
            print(f"[LOG] adb pair returncode: {result.returncode}")
            print(f"[LOG] adb pair stdout: {result.stdout}")
            print(f"[LOG] adb pair stderr: {result.stderr}")
            # 只要 returncode 非 0 或 stderr 有內容就降級
            if result.returncode != 0 or 'pair' in result.stderr or 'unknown command' in result.stderr or 'not recognized' in result.stderr:
                print('⚠️ adb 不支持 pair 或命令失敗，嘗試降級協議...')
                success = self.adb_pair_protocol(ip, port, self.password)
                if success:
                    print('配對成功!')
                    sys.exit(0)
                else:
                    print('配對失敗!')
                    sys.exit(1)
            if 'Successfully' in result.stdout:
                print('配對成功!')
                # 嘗試立刻連線到裝置
                # 配對成功後，需要尋找 connect port (通常是 _adb-tls-connect._tcp.local.)
                print(f'[LOG] 正在尋找連線埠 (IP: {ip})...')
                found_port = find_connect_port(ip)
                
                try_ports = []
                if found_port:
                    print(f'[LOG] 找到連線埠: {found_port}')
                    try_ports.append(found_port)
                else:
                    print(f'[LOG] 未能自動找到連線埠，嘗試使用預設埠與配對埠')
                
                # 加入使用者設定的埠與配對埠作為備案
                for p in self.connect_ports:
                    if p not in try_ports:
                        try_ports.append(p)
                if port not in try_ports:
                    try_ports.append(port)

                for try_port in try_ports:
                    try:
                        print(f"[LOG] 嘗試 adb connect {ip}:{try_port}")
                        rc = subprocess.run([ADB_PATH, 'connect', f'{ip}:{try_port}'], capture_output=True, text=True, timeout=10)
                        out = (rc.stdout or '') + (rc.stderr or '')
                        print(f"[LOG] adb connect returncode: {rc.returncode}")
                        print(f"[LOG] adb connect output: {out.strip()}")
                        if rc.returncode == 0 and ('connected to' in out.lower() or 'already connected' in out.lower()):
                            print('連線成功!')
                            sys.exit(0)
                    except Exception as e:
                        print(f"[LOG] 連線嘗試失敗: {e}")
                
                # 如果都失敗，但配對成功，還是退出 0 讓使用者自己嘗試? 或者退出 1?
                # 既然配對成功了，就當作成功吧，只是連線沒成功
                print('配對成功，但自動連線失敗。請手動確認埠號並連線。')
                sys.exit(0)
            else:
                print('配對失敗!')
                sys.exit(1)
        except Exception as e:
            print(f'[LOG] 配對過程出錯: {e}')
            sys.exit(1)

    def adb_pair_protocol(self, ip, port, password):
        print(f"[LOG] 嘗試降級協議 host:pair:{password}:{ip}:{port}")
        try:
            s = socket.create_connection(('127.0.0.1', 5037), timeout=5)
            cmd = f'host:pair:{password}:{ip}:{port}'
            msg = f'{len(cmd):04x}{cmd}'
            print(f"[LOG] 發送: {msg}")
            s.sendall(msg.encode('utf-8'))
            status = s.recv(4).decode('utf-8')
            print(f"[LOG] 回應狀態: {status}")
            if status == 'OKAY':
                print('降級協議回應: OKAY')
                s.close()
                return True
            elif status == 'FAIL':
                length_hex = s.recv(4).decode('utf-8')
                print(f"[LOG] FAIL 回應長度: {length_hex}")
                length = int(length_hex, 16)
                err_msg = s.recv(length).decode('utf-8')
                print(f'降級協議失敗: {err_msg}')
                s.close()
                return False
            else:
                print(f'未知回應: {status}')
                s.close()
                return False
        except Exception as e:
            print(f'[LOG] 降級協議過程出錯: {e}')
            return False

def get_adb_path():
    parser = argparse.ArgumentParser()
    parser.add_argument('--adb', type=str, default=None)
    args, _ = parser.parse_known_args()
    if args.adb:
        return args.adb
    import os
    return os.path.join(os.path.dirname(__file__), 'scrcpy-win64-v3.3', 'adb.exe')

ADB_PATH = get_adb_path()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--connect-only', action='store_true', help='只嘗試連線已配對的設備，失敗則退出')
    parser.add_argument('--connect-timeout', type=int, default=5, help='mDNS 掃描並嘗試連線的秒數')
    parser.add_argument('--connect-ports', type=str, default='5555', help='嘗試連線的埠清單，逗號分隔，例: 5555,5556')
    parser.add_argument('--service-id', type=str, default=None)
    parser.add_argument('--password', type=str, default=None)
    args, _ = parser.parse_known_args()
    # 優先用參數
    if args.service_id and args.password:
        service_id = args.service_id
        password = args.password
    else:
        service_id = "studio-" + random_string(8)
        password = random_string(8)
    adb_mdns_check()
    # 先嘗試通過 mDNS 找到並連線已配對的設備
    # 解析 connect ports 參數
    def parse_ports(ports_str):
        ports = []
        for p in ports_str.split(','):
            p = p.strip()
            if not p:
                continue
            try:
                ports.append(int(p))
            except ValueError:
                print(f'忽略無效埠: {p}')
        return ports

    connect_ports = parse_ports(args.connect_ports)

    def try_connect_via_mdns(timeout=5):
        zeroconf = Zeroconf()
        listener = ConnectListener(connect_ports)
        # 尋找 _adb-tls-connect._tcp.local. (連線服務) 而不是 pairing 服務
        browser = ServiceBrowser(zeroconf, '_adb-tls-connect._tcp.local.', listener)
        try:
            for _ in range(timeout):
                if listener.connected:
                    return True, listener.ip, listener.port
                time.sleep(1)
            return False, None, None
        finally:
            zeroconf.close()

    if args.connect_only:
        print('只執行連線嘗試 (connect-only) ...')
        ok, ip, port = try_connect_via_mdns(args.connect_timeout)
        if ok:
            print(f'已連線到 {ip}:{port}，退出')
            sys.exit(0)
        else:
            print('未找到可連線的已配對設備')
            sys.exit(1)

    print('先嘗試尋找並連線已配對設備 (若有的話) ...')
    ok, ip, port = try_connect_via_mdns(args.connect_timeout)
    if ok:
        print(f'已連線到 {ip}:{port}，不需要配對，退出')
        return
    print('如果設備已配對，可能已自動連接')
    print('若未配對，請在 Android 11+ 設備的開發者選項中開啟「無線調試」，選擇「通過二維碼配對」掃描下方二維碼')
    qr_data = f'WIFI:T:ADB;S:{service_id};P:{password};;'
    print_qr(qr_data)
    print(f'配對碼: serviceId={service_id} password={password}')

    zeroconf = Zeroconf()
    listener = AdbPairListener(service_id, password, connect_ports)
    browser = ServiceBrowser(zeroconf, '_adb-tls-pairing._tcp.local.', listener)
    print('正在搜尋可配對設備，請稍候... (60秒)')
    try:
        for _ in range(60):
            if listener.found:
                break
            time.sleep(1)
        else:
            print('未找到可配對設備，請確認手機已開啟無線調試並進入配對界面')
    finally:
        zeroconf.close()

if __name__ == '__main__':
    main()
