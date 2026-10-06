import asyncio
from asyncua import Client

# 데이터 변경 시 호출될 콜백 클래스
class SubHandler:
    def datachange_notification(self, node, val, data):
        print(f"[Client 수신] 데이터 변경 감지 노드 : {node}, 값: {val} 'C")

async def main():
    url = "opc.tcp://127.0.0.1:4840/freeopcua/server"
    client = Client(url=url)

    await client.connect()
    print("OPC-UA Server에 연결되었습니다.")

    try:
        # 서버 주소 공간에서 Temperature 노드 찾기
        # node = client.get_node("nc=1;s=MyDevice.Temperature") # 하드 코딩 방식

        # 서버에서 등록한 URI 기반 Namespace Index 동적 조회
        uri = "http://bylee.or.kr"
        idx = await client.get_namespace_index(uri)
        my_device = await client.nodes.objects.get_child(f"{idx}:MyDevice")
        temp_node = await my_device.get_child(f"{idx}:Temperature")

        print(f"찾은 노드 NodeId: {temp_node.nodeid}")

        # 구독 설정 객체 생성
        handler = SubHandler()
        subscription = await client.create_subscription(500, handler)

        # 구독 핸들러 연결
        handle = await subscription.subscribe_data_change(temp_node)
        print("Temperature 노드 구독이 시작되었습니다.")

        while True:
            await asyncio.sleep(1)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())