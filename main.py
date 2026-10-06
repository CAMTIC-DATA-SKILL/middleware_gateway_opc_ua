import asyncio
import logging

from config import config
from core.client.opc_ua import DataChange, OpcUaClient

logger = logging.getLogger("main")


class _PublishConnectionErrorFilter(logging.Filter):
    """재연결 대기 중 asyncua publish 루프가 매초 남기는 ConnectionError 트레이스백을 제외한다."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and isinstance(record.exc_info[1], ConnectionError):
            return not record.getMessage().startswith("Publish iteration crashed")
        return True


def setup_logging() -> None:
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    logging.getLogger("asyncua").setLevel(logging.WARNING)
    logging.getLogger("asyncua.client.ua_session.UaSession").addFilter(_PublishConnectionErrorFilter())


async def on_data_change(change: DataChange) -> None:
    logger.info(
        "[DataChange] %s = %r (status=%s, source_ts=%s)",
        change.node_id,
        change.value,
        change.status,
        change.source_timestamp,
    )


async def run() -> None:
    async with OpcUaClient() as client:
        node_ids = config.opcua.node_ids

        if not node_ids:
            logger.warning("OPCUA_NODE_IDS 가 비어 있어 Objects 하위 노드만 조회합니다.")
            for item in await client.browse():
                logger.info("[Browse] %s | %s | %s", item.node_id, item.browse_name, item.node_class)
            return

        for node_id, value in (await client.read_many(node_ids)).items():
            logger.info("[Read] %s = %r", node_id, value)

        await client.subscribe(node_ids, on_data_change)
        await asyncio.Event().wait()


def main() -> None:
    setup_logging()
    logger.info("middleware_gateway_opc_ua 시작 (endpoint=%s)", config.opcua.endpoint)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("middleware_gateway_opc_ua 종료")


if __name__ == "__main__":
    main()
