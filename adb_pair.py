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

# mDNS 服務發現
class AdbPairListener:
    def __init__(self, service_id, password):
        self.service_id = service_id
        self.password = password
        self.found = False

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
    print('如果設備已配對，可能已自動連接')
    print('若未配對，請在 Android 11+ 設備的開發者選項中開啟「無線調試」，選擇「通過二維碼配對」掃描下方二維碼')
    qr_data = f'WIFI:T:ADB;S:{service_id};P:{password};;'
    print_qr(qr_data)
    print(f'配對碼: serviceId={service_id} password={password}')
    adb_mdns_check()
    zeroconf = Zeroconf()
    listener = AdbPairListener(service_id, password)
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
