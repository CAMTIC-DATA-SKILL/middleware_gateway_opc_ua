"""
레포 전체 공통 로깅 설정.

진입점(main.py 등)에서 `setup_logging()` 을 한 번 호출하고,
각 모듈에서는 `get_logger(__name__)` 로 로거를 얻어 사용한다.

    from utils.log_setup import get_logger, setup_logging

    setup_logging()
    logger = get_logger(__name__)
"""

from __future__ import annotations

import logging

from config import config

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"

_LIBRARY_LEVELS = {
    "asyncua": logging.WARNING,
    # 표준 타입(AnalogItemType 등) 인스턴스 생성 시 타입 노드에 없는 속성마다 남기는 경고를 숨긴다.
    "asyncua.common.copy_node_util": logging.ERROR,
}

_configured = False


class _PublishConnectionErrorFilter(logging.Filter):
    """재연결 대기 중 asyncua publish 루프가 매초 남기는 ConnectionError 트레이스백을 제외한다."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and isinstance(record.exc_info[1], ConnectionError):
            return not record.getMessage().startswith("Publish iteration crashed")
        return True


def setup_logging(level: str | None = None) -> None:
    """여러 번 호출해도 핸들러가 중복 등록되지 않는다. level 미지정 시 LOG_LEVEL 환경변수를 따른다."""
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))

    root = logging.getLogger()
    root.setLevel(level or config.log_level)
    root.addHandler(handler)

    for name, library_level in _LIBRARY_LEVELS.items():
        logging.getLogger(name).setLevel(library_level)
    logging.getLogger("asyncua.client.ua_session.UaSession").addFilter(_PublishConnectionErrorFilter())

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
