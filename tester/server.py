import random
import asyncio
from asyncua import Server, Node, ua


async def main():
    # 서버 인스턴스 생성
    server = Server()
    await server.init()

    # 엔드포인트 설정 (로컬 테스트 용)
    server.set_endpoint("opc.tcp://0.0.0.0:4840/freeopcua/server/")

    # 네임스페이스 등록 및 객체 공간 구성
    uri = "http://bylee.or.kr"
    idx = await server.register_namespace(uri)

    # 루트 아래에 MyDevice 객체 생성
    objects = server.nodes.objects
    my_device = await objects.add_object(idx, "MyDevice")

    # MyDevice 하위에 Temperature 변수 노드 생성  (초기값 25.0으로 설정)
    temp_var = await my_device.add_variable(idx, "Temperature", 25.0)
    # 클라이언트가 이 값을 수정할 수 있도록 설정
    await temp_var.set_writable()


    print("OPC-UA Server is Start....")
    print("opc.tcp://127.0.0.1:4840")

    # 서버 구동 및 데이터 변경 루프
    async with server:
        while True:
            # 20.0 ~ 30.0 사이의 임의의 온도로 변경
            new_temp = round(random.uniform(20.0, 30.0), 2)
            await temp_var.write_value(new_temp)
            print(f"[Server 발행] 현재 온도 업데이트: {new_temp} 'C")
            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())