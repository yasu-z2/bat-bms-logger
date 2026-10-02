import asyncio
import csv
import datetime
from bleak import BleakClient

# ==========================================
# 設定項目
# ==========================================
BMS_ADDRESS = "A5:C2:37:51:C4:24"  # ご自身のMACアドレスを指定してください

NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"  # 受信窓口
WRITE_UUID  = "0000ff02-0000-1000-8000-00805f9b34fb"  # 送信窓口

LOG_FILE = "battery_log.csv"

# JBD/汎用BMS: 基本ステータス要求コマンド (0x03: 基本情報)
READ_BASIC_INFO_CMD = bytes.fromhex("DD A5 03 00 FF FD 77")

# 分割パケット結合用バッファ
rx_buffer = bytearray()


def handle_disconnect(client):
    print("\n[警告] バッテリーとの接続が切断されました。")


def parse_jbd_data(payload: bytes):
    """
    JBD/汎用BMSのレスポンス（Payload）を解析する
    Payload構造例:
      - [0:2]   : 総電圧 (mV / 10 または 10mV単位 -> /100.0でV)
      - [2:4]   : 電流 (10mA単位 -> 符号付き整数として処理)
      - [4:6]   : 残容量 (10mAh単位)
      - [19]    : 残量 SOC (%)
    """
    if len(payload) < 20:
        print("   ※データ長が足りないため詳細解析をスキップします。")
        return None

    try:
        # 総電圧 (10mV単位 -> V)
        voltage = int.from_bytes(payload[0:2], byteorder='big', signed=False) / 100.0
        
        # 電流 (10mA単位, 符号付き2の補数)
        current_raw = int.from_bytes(payload[2:4], byteorder='big', signed=True)
        current = current_raw / 100.0
        
        # 残容量 (10mAh -> Ah)
        rem_cap = int.from_bytes(payload[4:6], byteorder='big', signed=False) / 100.0
        
        # SOC (%) (通常20バイト目のインデックス19付近)
        soc = payload[19] if len(payload) > 19 else payload[18]

        print("--------------------------------------------------")
        print(f"  [解析結果] 電圧: {voltage:.2f} V | 電流: {current:.2f} A | 残容量: {rem_cap:.2f} Ah | SOC: {soc}%")
        print("--------------------------------------------------")
        return voltage, current, rem_cap, soc
    except Exception as e:
        print(f"   解析エラー: {e}")
        return None


def notification_handler(sender, data: bytearray):
    """分割送信されてくるBLEパケットをバッファに蓄積して解析"""
    global rx_buffer
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    rx_buffer.extend(data)
    hex_str = data.hex().upper()
    print(f"[{timestamp}] パケット受信: {hex_str} (現在バッファ長: {len(rx_buffer)}バイト)")

    # JBD系レスポンスの開始ヘッダー 0xDD と 終了フッター 0x77 のチェック
    if len(rx_buffer) >= 4 and rx_buffer[0] == 0xDD:
        # レスポンスフレーム全体の長さを確認 (3バイト目がデータ長)
        data_len = rx_buffer[3]
        expected_total_len = 7 + data_len  # ヘッダー(4) + データ(N) + チェックサム(2) + フッター(1)
        
        if len(rx_buffer) >= expected_total_len:
            frame = rx_buffer[:expected_total_len]
            rx_buffer = rx_buffer[expected_total_len:]  # 次のためにバッファをクリア
            
            full_hex = frame.hex().upper()
            print(f"\n★ 完全フレーム受信 (全{len(frame)}バイト): {full_hex}")
            
            # ペイロード（データ本体）抽出: 4バイト目から data_len 分
            payload = frame[4:4+data_len]
            parsed = parse_jbd_data(payload)
            
            # CSVログ保存
            v_val = parsed[0] if parsed else ""
            c_val = parsed[1] if parsed else ""
            soc_val = parsed[3] if parsed else ""
            
            with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, full_hex, v_val, c_val, soc_val])


async def main():
    # CSVヘッダー初期化
    try:
        with open(LOG_FILE, mode='x', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "RawHexData", "Voltage(V)", "Current(A)", "SOC(%)"])
    except FileExistsError:
        pass

    print(f"[{BMS_ADDRESS}] に接続中...")
    
    async with BleakClient(BMS_ADDRESS, disconnected_callback=handle_disconnect) as client:
        if client.is_connected:
            print("接続成功！データ要求を開始します。")
            await client.start_notify(NOTIFY_UUID, notification_handler)
            
            # 5秒おきにステータス要求コマンドを送信
            while True:
                try:
                    rx_buffer.clear()  # 送信前にバッファリセット
                    await client.write_gatt_char(WRITE_UUID, READ_BASIC_INFO_CMD, response=False)
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"送信エラー: {e}")
                    await asyncio.sleep(5)

            await client.stop_notify(NOTIFY_UUID)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nプログラムを停止しました。")