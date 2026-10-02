import asyncio
import csv
import datetime
from bleak import BleakClient

# ==========================================
# 設定項目
# ==========================================
# ご自身のMACアドレスを指定してください
BMS_ADDRESS = ""

# 調査結果に基づく正しいUUID設定
NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"  # 受用窓口
WRITE_UUID  = "0000ff02-0000-1000-8000-00805f9b34fb"  # 送信窓口

# 保存するログファイル名
LOG_FILE = "battery_log.csv"

# 代表的なBMSのリクエストコマンド候補（複数試行用）
# BAT-BMS系汎用コマンド / Daly / JBD系コマンド例
COMMANDS_TO_TEST = [
    bytes.fromhex("00 00 04 01 13 55 AA 17"),     # 汎用パターン1
    bytes.fromhex("DD A5 03 00 FF FD 77"),        # 汎用パターン2 (JBD/Daly系)
    bytes.fromhex("00"),                          # 単一リクエスト
    bytes.fromhex("A5 40 90 08 00 00 00 00 00 00 00 00 38"), # 汎用パターン3
]


def handle_disconnect(client):
    print("\n[警告] バッテリーとの接続が切断されました。")


def notification_handler(sender, data: bytearray):
    """バッテリーからデータを受信したときに呼ばれるコールバック関数"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # バイト列を16進数文字列（Hex）に変換
    hex_data = data.hex().upper()
    print(f"\n★ [{timestamp}] 受信データ (Hex): {hex_data}")
    print(f"   データ長: {len(data)} バイト")
    
    # CSVファイルへ追記保存
    with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, hex_data])


async def main():
    # CSVファイルの初期化（ヘッダー書き込み）
    try:
        with open(LOG_FILE, mode='x', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "RawHexData"])
    except FileExistsError:
        pass

    print(f"[{BMS_ADDRESS}] に接続を試みています...")
    
    async with BleakClient(BMS_ADDRESS, disconnected_callback=handle_disconnect) as client:
        if client.is_connected:
            print("接続成功！データ受信を開始します。")
            
            # データ受信の通知（Notify）を開始
            await client.start_notify(NOTIFY_UUID, notification_handler)
            
            print("\nコマンドを順番に送信してバッテリーの反応を確認します...")
            
            # 各コマンドパターンを試すループ
            while True:
                for idx, cmd in enumerate(COMMANDS_TO_TEST, 1):
                    print(f"-> コマンドパターン {idx} 送信中: {cmd.hex().upper()}")
                    try:
                        # response=False (write-without-response) で送信
                        await client.write_gatt_char(WRITE_UUID, cmd, response=False)
                    except Exception as e:
                        print(f"   送信エラー: {e}")
                    
                    # 受信待機
                    await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nプログラムを停止しました。")