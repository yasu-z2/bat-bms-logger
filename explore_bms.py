import asyncio
from bleak import BleakClient

# MACアドレスを指定
BMS_ADDRESS = "A5:C2:37:51:C4:24"  # ご自身のMACアドレスに書き換えてください


async def explore_services():
    print(f"[{BMS_ADDRESS}] に接続して通信窓口(GATT Services)を調査中...")
    
    async with BleakClient(BMS_ADDRESS) as client:
        if client.is_connected:
            print("\n接続成功！ 利用可能なサービスとキャラクタリスティック一覧:\n")
            
            for service in client.services:
                print(f"■ Service: {service.uuid} ({service.description})")
                for char in service.characteristics:
                    props = ", ".join(char.properties)
                    print(f"   └─ Characteristic: {char.uuid}")
                    print(f"      属性 (Properties): [{props}]")
                    print(f"      ハンドル (Handle): {char.handle}")
                print()


if __name__ == "__main__":
    try:
        asyncio.run(explore_services())
    except Exception as e:
        print(f"エラーが発生しました: {e}")