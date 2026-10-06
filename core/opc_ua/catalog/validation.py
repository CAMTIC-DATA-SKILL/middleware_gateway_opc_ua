from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from core.opc_ua.catalog.model import Catalog, CatalogTag, TagStatus
from core.opc_ua.catalog.types import NUMERIC_DATA_TYPES, SUPPORTED_DATA_TYPES
from core.opc_ua.catalog.units import lookup_unit
from utils.log_setup import get_logger

logger = get_logger(__name__)

RESERVED_NAME = "_Gateway"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class CatalogIssue:
    severity: Severity
    tag_id: str
    message: str


@dataclass
class ValidationResult:
    checked_count: int = 0
    issues: list[CatalogIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[CatalogIssue]:
        return [issue for issue in self.issues if issue.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[CatalogIssue]:
        return [issue for issue in self.issues if issue.severity is Severity.WARNING]

    @property
    def invalid_tag_ids(self) -> set[str]:
        return {issue.tag_id for issue in self.errors}


def validate_catalog(catalog: Catalog) -> ValidationResult:
    """
    운영에 쓰이는 `enabled: true` 태그만 검사한다.

    오류가 있는 태그는 실행 시 제외되고, 경고는 동작에 영향이 없지만 확인이 필요한 항목이다.
    """
    result = ValidationResult()
    enabled = [tag for tag in catalog.tags if tag.enabled]
    result.checked_count = len(enabled)

    object_node_ids = {
        "/".join(tag.target.segments[:depth])
        for tag in enabled
        for depth in range(1, len(tag.target.segments) + 1)
    }
    used_names: dict[tuple[tuple[str, ...], str], str] = {}

    for tag in enabled:
        issues = _check_tag(tag)

        if tag.tag_id in object_node_ids:
            issues.append(_error(tag, f"tag_id 가 다른 태그의 객체 경로와 같아 NodeId 가 충돌합니다: {tag.tag_id}"))

        if not any(issue.severity is Severity.ERROR for issue in issues):
            name_key = (tag.target.segments, tag.target.name)
            if name_key in used_names:
                full_name = "/".join((*tag.target.segments, tag.target.name))
                issues.append(_error(tag, f"'{full_name}' 이(가) 태그 {used_names[name_key]} 와 겹칩니다."))
            else:
                used_names[name_key] = tag.tag_id

        result.issues.extend(issues)
    return result


def _check_tag(tag: CatalogTag) -> list[CatalogIssue]:
    issues: list[CatalogIssue] = []
    source, target = tag.source, tag.target

    if not source.namespace_uri or not source.identifier:
        issues.append(_error(tag, "source.namespace_uri 와 source.identifier 는 비워 둘 수 없습니다."))

    if not target.name:
        issues.append(_error(tag, "target.name 은 비워 둘 수 없습니다."))
    elif "/" in target.name:
        issues.append(_error(tag, f"target.name 에는 '/' 를 쓸 수 없습니다: {target.name!r}"))

    if tag.tag_id.startswith(RESERVED_NAME) or (target.segments and target.segments[0] == RESERVED_NAME):
        issues.append(_error(tag, f"'{RESERVED_NAME}' 은(는) 게이트웨이 상태 노드용으로 예약된 이름입니다."))

    numeric = target.data_type in NUMERIC_DATA_TYPES
    if target.data_type not in SUPPORTED_DATA_TYPES:
        supported = ", ".join(sorted(SUPPORTED_DATA_TYPES))
        issues.append(_error(tag, f"지원하지 않는 target.data_type 입니다: {target.data_type!r} (사용 가능: {supported})"))
    elif target.unit and not numeric:
        issues.append(_warning(tag, f"숫자 형식이 아니므로 unit({target.unit!r}) 은 무시됩니다."))
    elif target.unit and lookup_unit(target.unit) is None:
        issues.append(_warning(tag, f"표준 단위 코드를 찾지 못해 표시 이름({target.unit!r})만 제공합니다."))

    if target.eu_range is not None:
        low, high = target.eu_range.low, target.eu_range.high
        if not (_is_number(low) and _is_number(high)):
            issues.append(_error(tag, "target.eu_range 의 low, high 는 숫자여야 합니다."))
        elif low >= high:
            issues.append(_error(tag, f"target.eu_range 의 low({low}) 는 high({high}) 보다 작아야 합니다."))
        elif not numeric and target.data_type in SUPPORTED_DATA_TYPES:
            issues.append(_warning(tag, "숫자 형식이 아니므로 eu_range 는 무시됩니다."))

    collection = tag.collection
    if not _is_number(collection.sampling_interval_ms) or collection.sampling_interval_ms < 0:
        issues.append(_error(tag, "collection.sampling_interval_ms 는 0 이상의 숫자여야 합니다."))
    if not _is_number(collection.publishing_interval_ms) or collection.publishing_interval_ms <= 0:
        issues.append(_error(tag, "collection.publishing_interval_ms 는 0 보다 큰 숫자여야 합니다."))
    if not _is_number(collection.deadband) or collection.deadband < 0:
        issues.append(_error(tag, "collection.deadband 는 0 이상의 숫자여야 합니다."))

    if not (_is_number(tag.conversion.scale) and _is_number(tag.conversion.offset)):
        issues.append(_error(tag, "conversion.scale, conversion.offset 은 숫자여야 합니다."))

    if tag.status is TagStatus.CANDIDATE:
        issues.append(_warning(tag, "검토 전(candidate) 태그가 활성화되어 있습니다."))
    elif tag.status is TagStatus.DISABLED:
        issues.append(_warning(tag, "status 는 disabled 인데 enabled 가 true 입니다."))

    return issues


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _error(tag: CatalogTag, message: str) -> CatalogIssue:
    return CatalogIssue(Severity.ERROR, tag.tag_id, message)


def _warning(tag: CatalogTag, message: str) -> CatalogIssue:
    return CatalogIssue(Severity.WARNING, tag.tag_id, message)


def log_validation(result: ValidationResult) -> None:
    for issue in result.issues:
        if issue.severity is Severity.ERROR:
            logger.error("[오류] %s - %s", issue.tag_id, issue.message)
        else:
            logger.warning("[경고] %s - %s", issue.tag_id, issue.message)
    logger.info(
        "카탈로그 검증: 활성 태그 %d개 / 오류 %d건 (제외 태그 %d개), 경고 %d건",
        result.checked_count,
        len(result.errors),
        len(result.invalid_tag_ids),
        len(result.warnings),
    )
