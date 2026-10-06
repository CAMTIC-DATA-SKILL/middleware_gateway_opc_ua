import argparse
import asyncio
from pathlib import Path

from asyncua import ua

from config import config
from core.catalog import load_catalog, save_catalog
from core.client.opc_ua import DataChange, OpcUaClient
from core.discovery import DiscoveryService, log_report
from utils.log_setup import get_logger, setup_logging

logger = get_logger("main")


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


async def discover(args: argparse.Namespace) -> None:
    catalog_path: Path = args.output
    catalog = load_catalog(catalog_path)

    async with OpcUaClient() as client:
        try:
            report = await DiscoveryService(client, config.opcua).discover(
                catalog,
                root=args.root,
                max_depth=args.max_depth,
                max_nodes=args.max_nodes,
            )
        except ValueError as e:
            logger.error("탐색 실패: %s", e)
            return

    log_report(report)
    if args.dry_run:
        logger.info("--dry-run: 카탈로그 파일을 저장하지 않았습니다.")
    elif report.added:
        save_catalog(catalog, catalog_path)
        logger.info("카탈로그 저장: %s (신규 후보 %d개 추가)", catalog_path, len(report.added))
    else:
        logger.info("추가할 신규 태그가 없어 카탈로그를 변경하지 않았습니다.")


def _node_id(text: str) -> ua.NodeId:
    try:
        return ua.NodeId.from_string(text)
    except Exception as e:
        raise argparse.ArgumentTypeError(f"올바른 NodeId 형식이 아닙니다: {text!r}") from e


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OPC-UA middleware gateway")
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("run", help="게이트웨이 실행 (기본값)")

    discover_parser = commands.add_parser("discover", help="현장 서버를 탐색해 태그 카탈로그 후보를 생성")
    discover_parser.add_argument(
        "--root",
        type=_node_id,
        help="탐색 시작 NodeId (기본값: Objects 폴더). 예) ns=2;s=Line01",
    )
    discover_parser.add_argument("--max-depth", type=int, default=10, help="최대 탐색 깊이 (기본값: 10)")
    discover_parser.add_argument("--max-nodes", type=int, default=50_000, help="최대 탐색 노드 수 (기본값: 50000)")
    discover_parser.add_argument(
        "--output",
        type=Path,
        default=config.catalog_path,
        help=f"카탈로그 파일 경로 (기본값: {config.catalog_path})",
    )
    discover_parser.add_argument("--dry-run", action="store_true", help="결과만 출력하고 파일은 저장하지 않음")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging()
    command = args.command or "run"
    logger.info("middleware_gateway_opc_ua 시작 (command=%s, endpoint=%s)", command, config.opcua.endpoint)
    try:
        asyncio.run(discover(args) if command == "discover" else run())
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("middleware_gateway_opc_ua 종료")


if __name__ == "__main__":
    main()
