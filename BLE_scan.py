import asyncio
from bleak import BleakScanner

async def scan():
    print("BLEデバイスをスキャン中... (約5秒間)")
    devices = await BleakScanner.discover(timeout=5.0)
    
    print("\n--- 検出されたデバイス一覧 ---")
    for d in devices:
        # 名前が存在するデバイスを表示
        if d.name:
            print(f"名前: {d.name:<25} | アドレス: {d.address}")

if __name__ == "__main__":
    asyncio.run(scan())