"""
프로젝트 전역 설정.

프로젝트 루트의 `.env` 파일을 읽어 설정 객체를 구성한다.
다른 모듈에서는 아래와 같이 import 해서 사용한다.

    from config import config

    config.log_level
    config.opcua.endpoint
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)

_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "no", "n", "off"}


def _get_str(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _get_optional_str(key: str) -> str | None:
    return _get_str(key) or None


def _get_int(key: str, default: int) -> int:
    raw = _get_str(key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ValueError(f"환경변수 {key} 는 정수여야 합니다: {raw!r}") from e


def _get_float(key: str, default: float) -> float:
    raw = _get_str(key)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as e:
        raise ValueError(f"환경변수 {key} 는 실수여야 합니다: {raw!r}") from e


def _get_bool(key: str, default: bool) -> bool:
    raw = _get_str(key).lower()
    if not raw:
        return default
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    raise ValueError(f"환경변수 {key} 는 bool 값이어야 합니다: {raw!r}")


def _get_list(key: str, sep: str = ",") -> tuple[str, ...]:
    raw = _get_str(key)
    if not raw:
        return ()
    return tuple(item.strip() for item in raw.split(sep) if item.strip())


def _get_path(key: str) -> Path | None:
    raw = _get_optional_str(key)
    if raw is None:
        return None
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path


@dataclass(frozen=True)
class OpcUaConfig:
    endpoint: str
    client_name: str
    application_uri: str

    timeout: float
    watchdog_interval: float
    session_timeout_ms: int

    auto_reconnect: bool
    reconnect_max_delay: float
    connect_retry_interval: float
    connect_max_retries: int

    username: str | None
    password: str | None

    security_policy: str
    security_mode: str
    client_cert: Path | None
    client_key: Path | None
    server_cert: Path | None

    subscription_period_ms: int
    sampling_interval_ms: int
    node_ids: tuple[str, ...]

    @property
    def use_security(self) -> bool:
        return self.security_policy.lower() != "none"


@dataclass(frozen=True)
class AppConfig:
    base_dir: Path
    log_level: str
    opcua: OpcUaConfig


def load_config() -> AppConfig:
    opcua = OpcUaConfig(
        endpoint=_get_str("OPCUA_ENDPOINT", "opc.tcp://localhost:4840"),
        client_name=_get_str("OPCUA_CLIENT_NAME", "middleware_gateway_opc_ua"),
        application_uri=_get_str("OPCUA_APPLICATION_URI", "urn:middleware:gateway:opcua:client"),
        timeout=_get_float("OPCUA_TIMEOUT", 4.0),
        watchdog_interval=_get_float("OPCUA_WATCHDOG_INTERVAL", 1.0),
        session_timeout_ms=_get_int("OPCUA_SESSION_TIMEOUT_MS", 3_600_000),
        auto_reconnect=_get_bool("OPCUA_AUTO_RECONNECT", True),
        reconnect_max_delay=_get_float("OPCUA_RECONNECT_MAX_DELAY", 30.0),
        connect_retry_interval=_get_float("OPCUA_CONNECT_RETRY_INTERVAL", 5.0),
        connect_max_retries=_get_int("OPCUA_CONNECT_MAX_RETRIES", 0),
        username=_get_optional_str("OPCUA_USERNAME"),
        password=_get_optional_str("OPCUA_PASSWORD"),
        security_policy=_get_str("OPCUA_SECURITY_POLICY", "None"),
        security_mode=_get_str("OPCUA_SECURITY_MODE", "SignAndEncrypt"),
        client_cert=_get_path("OPCUA_CLIENT_CERT"),
        client_key=_get_path("OPCUA_CLIENT_KEY"),
        server_cert=_get_path("OPCUA_SERVER_CERT"),
        subscription_period_ms=_get_int("OPCUA_SUBSCRIPTION_PERIOD_MS", 500),
        sampling_interval_ms=_get_int("OPCUA_SAMPLING_INTERVAL_MS", 100),
        node_ids=_get_list("OPCUA_NODE_IDS"),
    )

    if opcua.use_security and not (opcua.client_cert and opcua.client_key):
        raise ValueError(
            "OPCUA_SECURITY_POLICY 가 None 이 아니면 OPCUA_CLIENT_CERT, OPCUA_CLIENT_KEY 가 필요합니다."
        )

    return AppConfig(
        base_dir=BASE_DIR,
        log_level=_get_str("LOG_LEVEL", "INFO").upper(),
        opcua=opcua,
    )


config = load_config()
