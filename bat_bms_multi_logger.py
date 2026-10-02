import os
import sys
import csv
import asyncio
from datetime import datetime
from bleak import BleakScanner
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# 設定項目
# ==========================================
# 取得対象のBMS設定
BMS_TARGETS = {
    "SOLAR1": "A4:C1:38:XX:XX:XX",  # ※ご環境のMACアドレスに合わせてください
    "SOLAR2": "A4:C1:38:YY:YY:YY"   # ※ご環境のMACアドレスに合わせてください
}

# Googleドライブの保存先フォルダーID（各自の環境に合わせて変更してください）
GDRIVE_FOLDER_ID = "YOUR_GDRIVE_FOLDER_ID_HERE"

# 保存・転送するCSVファイル名
LOCAL_CSV_FILENAME = "battery_data_latest.csv"

# ==========================================
# ファイルパス・認証設定
# ==========================================
# PyInstallerでEXE化された場合と通常の.py実行時のどちらでも
# 実行ファイル本体と同じフォルダーにあるサービスアカウントキーを参照する設定
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, "service_account.json")
LOCAL_CSV_PATH = os.path.join(BASE_DIR, LOCAL_CSV_FILENAME)


# ==========================================
# BMSデータ取得処理 (BLE)
# ==========================================
async def get_bms_data(name, mac_address):
    """指定したMACアドレスのBMSからデータを取得"""
    print(f"{name} データを取得中...")
    
    # スキャン試行 (10秒間)
    devices = await BleakScanner.discover(timeout=10.0)
    target_device = None
    
    for d in devices:
        if d.address.upper() == mac_address.upper():
            target_device = d
            break

    if not target_device:
        print(f"  [{name}] デバイスが見つかりませんでした ({mac_address})")
        return None

    # アドバタイズメントデータまたは接続から電圧/SOCを取得する処理
    # (既存のBMS解析ロジックをここに配置)
    # 以下はサンプル値のプレースホルダーです
    voltage = 13.3
    soc = 95 if name == "SOLAR1" else 96

    print(f"  [{name}] 電圧: {voltage}V | SOC: {soc}%")
    return {
        "name": name,
        "voltage": voltage,
        "soc": soc
    }


# ==========================================
# CSV保存処理
# ==========================================
def save_to_csv(data_list, output_path):
    """取得したデータをローカルのCSVファイルへ保存"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # ヘッダーと行データの構築
    headers = ["Timestamp"]
    row = [now_str]
    
    for item in data_list:
        if item:
            headers.extend([f"{item['name']}_Voltage", f"{item['name']}_SOC"])
            row.extend([item['voltage'], item['soc']])
        else:
            headers.extend(["N/A", "N/A"])
            row.extend(["", ""])

    with open(output_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerow(row)
        
    print(f"ローカルCSVファイルを出力しました: {output_path}")


# ==========================================
# Googleドライブ転送処理 (Drive API v3)
# ==========================================
def upload_csv_to_gdrive(local_file_path):
    """Googleドライブの指定フォルダーへCSVを転送（既存ファイルは上書き更新）"""
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(f"認証ファイルが見つかりません: {SERVICE_ACCOUNT_FILE}")

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
        # 既存ファイルを上書き更新（所有権が変わらないためクォータエラーになりません）
        file_id = items[0]['id']
        service.files().update(
            fileId=file_id,
            media_body=media,
            supportsAllDrives=True
        ).execute()
        print(f"Googleドライブ上のファイル ({LOCAL_CSV_FILENAME}) を更新しました！")
    else:
        # 新規ファイル作成の試行
        try:
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
        except Exception as e:
            if "storageQuotaExceeded" in str(e):
                print("\n【エラー対処ガイド】")
                print(f"Googleドライブのフォルダー（ID: {GDRIVE_FOLDER_ID}）内に、")
                print(f"手動で空の '{LOCAL_CSV_FILENAME}' を作成してください。")
            raise e


# ==========================================
# メイン処理
# ==========================================
async def main():
    print(f"--- バッテリーデータ自動取得・CSV出力開始 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ---")
    
    # 1. 各BMSからデータ取得
    results = []
    for name, mac in BMS_TARGETS.items():
        data = await get_bms_data(name, mac)
        results.append(data)
        
    # 2. ローカルCSV保存
    save_to_csv(results, LOCAL_CSV_PATH)
    
    # 3. Googleドライブへ転送
    upload_csv_to_gdrive(LOCAL_CSV_PATH)
    print("すべての処理が正常に完了しました。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\n予期せぬエラーが発生しました: {e}")
    finally:
        # EXE実行時に画面がすぐ閉じないよう待機処理を追加
        if getattr(sys, 'frozen', False):
            input("\nEnterキーを押すと終了します...")