import asyncio
import datetime
import os
import csv
from bleak import BleakClient, BleakError

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# 設定項目
# ==========================================
# モニタリング対象バッテリー情報
BATTERIES = [
    {"name": "SOLAR1", "address": "A5:C2:37:51:C4:24"},
    {"name": "SOLAR2", "address": "A5:C2:37:51:C3:5C"},
]

# 保存先の Google ドライブ フォルダー ID
GDRIVE_FOLDER_ID = "1Ztlq-xpDLKJ8BbGwQQuOnnG6r81KN7PU"

# 認証キーJSONファイルの絶対パスを取得（スクリプトと同階層）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, "service_account.json")

# 出力するCSVファイル名（ローカル生成用 兼 Googleドライブ上のファイル名）
LOCAL_CSV_FILENAME = "battery_data_latest.csv"

# 通信UUID（JBD/BAT-BMS規格）
NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
WRITE_UUID  = "0000ff02-0000-1000-8000-00805f9b34fb"

# JBDプロトコル: 基本ステータス要求コマンド (0x03 コマンド)
READ_BASIC_INFO_CMD = bytes.fromhex("DD A5 03 00 FF FD 77")


def parse_jbd_payload(payload: bytes):
    """JBD/BAT-BMSの受信ペイロードを解析して各ステータス値を抽出"""
    if len(payload) < 24:
        return None

    try:
        # 1. 総電圧 (10mV単位 -> V)
        voltage = int.from_bytes(payload[0:2], byteorder='big', signed=False) / 100.0

        # 2. 電流 (10mA単位, 符号付き: プラス=充電 / マイナス=放電)
        current_raw = int.from_bytes(payload[2:4], byteorder='big', signed=True)
        current = current_raw / 100.0

        # 3. 電力 (W)
        power = round(voltage * current, 2)

        # 4. 残容量 (10mAh単位 -> Ah)
        rem_cap = int.from_bytes(payload[4:6], byteorder='big', signed=False) / 100.0

        # 5. SOC 残量 (%)
        soc = payload[19]

        # 6. BMS温度 (°K * 10 ➔ °C に変換)
        temp_raw = int.from_bytes(payload[23:25], byteorder='big', signed=False)
        temp_c = round((temp_raw - 2731) / 10.0, 1) if temp_raw > 0 else 0.0

        return {
            "voltage": voltage,
            "current": current,
            "power": power,
            "rem_cap": rem_cap,
            "soc": soc,
            "temp_c": temp_c
        }
    except Exception as e:
        print(f"解析エラー: {e}")
        return None


async def fetch_battery_data(target):
    """単一バッテリーに接続してデータを1回取得"""
    name = target["name"]
    address = target["address"]
    
    received_data = None
    rx_buffer = bytearray()
    data_event = asyncio.Event()

    def notification_handler(sender, data: bytearray):
        nonlocal received_data, rx_buffer
        rx_buffer.extend(data)

        if len(rx_buffer) >= 4 and rx_buffer[0] == 0xDD:
            data_len = rx_buffer[3]
            expected_total_len = 7 + data_len

            if len(rx_buffer) >= expected_total_len:
                frame = rx_buffer[:expected_total_len]
                payload = frame[4:4+data_len]
                received_data = parse_jbd_payload(payload)
                data_event.set()

    try:
        async with BleakClient(address, timeout=15.0) as client:
            if client.is_connected:
                await asyncio.sleep(0.5)
                await client.start_notify(NOTIFY_UUID, notification_handler)
                await asyncio.sleep(0.2)
                await client.write_gatt_char(WRITE_UUID, READ_BASIC_INFO_CMD, response=False)
                
                try:
                    await asyncio.wait_for(data_event.wait(), timeout=6.0)
                except asyncio.TimeoutError:
                    print(f"[{name}] 応答タイムアウト")

                await client.stop_notify(NOTIFY_UUID)

    except Exception as e:
        print(f"[{name}] 接続エラー: {e}")

    return received_data


def create_local_csv(timestamp, s1_data, s2_data):
    """ローカルに書き込み用CSVファイルを一時生成"""
    file_path = os.path.join(BASE_DIR, LOCAL_CSV_FILENAME)
    
    v1 = s1_data['voltage'] if s1_data else ""
    c1 = s1_data['current'] if s1_data else ""
    soc1 = s1_data['soc'] if s1_data else ""

    v2 = s2_data['voltage'] if s2_data else ""
    c2 = s2_data['current'] if s2_data else ""
    soc2 = s2_data['soc'] if s2_data else ""

    headers = ["日時", "電圧1(V)", "電圧2(V)", "SOC1(%)", "SOC2(%)", "電流1(A)", "電流2(A)"]
    row_values = [timestamp, v1, v2, soc1, soc2, c1, c2]

    with open(file_path, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerow(row_values)

    return file_path


def upload_csv_to_gdrive(local_file_path):
    """Googleドライブの指定フォルダーへCSVを転送（既存ファイルは上書き更新）"""
    scopes = ['https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    service = build('drive', 'v3', credentials=creds)

    # 1. 指定フォルダー内に同名の既存ファイルが存在するか検索
    query = f"'{GDRIVE_FOLDER_ID}' in parents and name = '{LOCAL_CSV_FILENAME}' and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    items = results.get('files', [])

    media = MediaFileUpload(local_file_path, mimetype='text/csv', resumable=False)

    if items:
        # 既存ファイルを上書き更新
        file_id = items[0]['id']
        service.files().update(
            fileId=file_id,
            media_body=media,
            supportsAllDrives=True
        ).execute()
        print(f"Googleドライブ上のファイル ({LOCAL_CSV_FILENAME}) を更新しました！")
    else:
        # 新規ファイル作成
        file_metadata = {
            'name': LOCAL_CSV_FILENAME,
            'parents': [GDRIVE_FOLDER_ID]
        }
        service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute()
        print(f"Googleドライブへ新規ファイル ({LOCAL_CSV_FILENAME}) を書き込みました！")


async def main():
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"--- バッテリーデータ自動取得・CSV出力開始 [{timestamp}] ---")

    # SOLAR1 データ取得
    print("SOLAR1 データを取得中...")
    s1_res = await fetch_battery_data(BATTERIES[0])
    if s1_res:
        print(f"  [SOLAR1] 電圧: {s1_res['voltage']}V | SOC: {s1_res['soc']}%")
    else:
        print("  [SOLAR1] 取得失敗")

    await asyncio.sleep(2.0)

    # SOLAR2 データ取得
    print("SOLAR2 データを取得中...")
    s2_res = await fetch_battery_data(BATTERIES[1])
    if s2_res:
        print(f"  [SOLAR2] 電圧: {s2_res['voltage']}V | SOC: {s2_res['soc']}%")
    else:
        print("  [SOLAR2] 取得失敗")

    # どちらか一方でも取得できれば処理を続行
    if s1_res or s2_res:
        local_path = create_local_csv(timestamp, s1_res, s2_res)
        upload_csv_to_gdrive(local_path)
    else:
        print("両方のバッテリーデータ取得に失敗したため、ファイル書き込みをスキップしました。")


if __name__ == "__main__":
    asyncio.run(main())