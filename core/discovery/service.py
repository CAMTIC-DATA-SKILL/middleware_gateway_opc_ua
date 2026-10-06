from __future__ import annotations

import re
from dataclasses import dataclass, field

from asyncua import ua

from config import OpcUaConfig
from core.catalog import (
    Catalog,
    CatalogTag,
    CollectionSpec,
    SourceSpec,
    TagStatus,
    TargetSpec,
)
from core.client.opc_ua import OpcUaClient
from core.discovery.browser import AddressSpaceBrowser, DiscoveredVariable
from utils.log_setup import get_logger

logger = get_logger(__name__)

_NON_WORD = re.compile(r"\W+")


@dataclass
class TagChange:
    tag: CatalogTag
    fields: dict[str, tuple[str, str]]


@dataclass
class DiscoveryReport:
    visited_count: int = 0
    variable_count: int = 0
    truncated: bool = False
    missing_checked: bool = True
    added: list[CatalogTag] = field(default_factory=list)
    changed: list[TagChange] = field(default_factory=list)
    missing: list[CatalogTag] = field(default_factory=list)
    unchanged_count: int = 0


class DiscoveryService:
    """
    현장 서버를 탐색한 결과를 기존 카탈로그와 비교해 반영한다.

    - 새로 발견된 노드는 `candidate` 상태, 비활성(`enabled: false`)으로 추가한다.
    - 이미 카탈로그에 있는 태그는 운영자가 검토한 내용이므로 수정하지 않고 변경 사항만 보고한다.
    - 카탈로그에는 있으나 서버에서 찾지 못한 태그도 삭제하지 않고 보고만 한다.
    """

    def __init__(self, client: OpcUaClient, cfg: OpcUaConfig) -> None:
        self._client = client
        self._cfg = cfg

    async def discover(
        self,
        catalog: Catalog,
        root: ua.NodeId | None = None,
        max_depth: int = 10,
        max_nodes: int = 50_000,
    ) -> DiscoveryReport:
        browser = AddressSpaceBrowser(self._client.client, max_depth=max_depth, max_nodes=max_nodes)
        result = await browser.browse(root)

        report = DiscoveryReport(
            visited_count=result.visited_count,
            variable_count=len(result.variables),
            truncated=result.truncated,
            # 일부만 탐색한 경우, 탐색 범위 밖의 태그가 누락으로 잘못 보고되지 않도록 한다.
            missing_checked=root is None and not result.truncated,
        )

        existing = catalog.by_source_key()
        used_ids = catalog.tag_ids
        found_keys: set[tuple[str, str, str]] = set()

        for variable in result.variables:
            source = self._to_source(variable)
            found_keys.add(source.key)

            current = existing.get(source.key)
            if current is None:
                tag = self._to_tag(variable, source, used_ids)
                used_ids.add(tag.tag_id)
                catalog.tags.append(tag)
                report.added.append(tag)
                continue

            changes = {
                name: (old, new)
                for name, old, new in (
                    ("browse_path", current.source.browse_path, source.browse_path),
                    ("data_type", current.source.data_type, source.data_type),
                )
                if old != new
            }
            if changes:
                report.changed.append(TagChange(current, changes))
            else:
                report.unchanged_count += 1

        if report.missing_checked:
            report.missing = [
                tag
                for key, tag in existing.items()
                if tag.source.server == self._cfg.server_id and key not in found_keys
            ]
        return report

    def _to_source(self, variable: DiscoveredVariable) -> SourceSpec:
        return SourceSpec(
            server=self._cfg.server_id,
            namespace_uri=variable.namespace_uri,
            identifier=variable.identifier,
            browse_path="/".join(variable.browse_path),
            data_type=variable.data_type,
        )

    def _to_tag(self, variable: DiscoveredVariable, source: SourceSpec, used_ids: set[str]) -> CatalogTag:
        parent_path = variable.browse_path[:-1]
        return CatalogTag(
            tag_id=self._make_tag_id(variable.browse_path, used_ids),
            name=variable.display_name,
            description=variable.description,
            enabled=False,
            status=TagStatus.CANDIDATE,
            source=source,
            target=TargetSpec(
                path="/".join((self._cfg.server_id, *parent_path)),
                name=variable.browse_path[-1],
                data_type=variable.data_type,
                unit=variable.unit,
            ),
            collection=CollectionSpec(
                sampling_interval_ms=self._cfg.sampling_interval_ms,
                publishing_interval_ms=self._cfg.subscription_period_ms,
            ),
        )

    def _make_tag_id(self, browse_path: tuple[str, ...], used_ids: set[str]) -> str:
        parts = [_NON_WORD.sub("_", part).strip("_").lower() for part in (self._cfg.server_id, *browse_path)]
        base = ".".join(part for part in parts if part)
        tag_id, suffix = base, 2
        while tag_id in used_ids:
            tag_id, suffix = f"{base}_{suffix}", suffix + 1
        return tag_id


def log_report(report: DiscoveryReport) -> None:
    logger.info(
        "탐색 완료: 노드 %d개, 변수 %d개 / 신규 %d, 변경 %d, 누락 %s, 동일 %d",
        report.visited_count,
        report.variable_count,
        len(report.added),
        len(report.changed),
        len(report.missing) if report.missing_checked else "확인 안 함",
        report.unchanged_count,
    )
    for tag in report.added:
        logger.info("[신규] %s (%s, %s)", tag.tag_id, tag.source.browse_path, tag.source.data_type or "-")
    for change in report.changed:
        details = ", ".join(f"{name}: {old!r} -> {new!r}" for name, (old, new) in change.fields.items())
        logger.warning("[변경] %s - %s", change.tag.tag_id, details)
    for tag in report.missing:
        logger.warning("[누락] %s (%s) - 서버에서 노드를 찾지 못했습니다.", tag.tag_id, tag.source.browse_path)
    if report.truncated:
        logger.warning("탐색이 노드 수 상한에서 중단되어 결과가 일부만 반영되었습니다.")
    elif not report.missing_checked:
        logger.info("--root 로 일부만 탐색했으므로 누락 확인은 생략했습니다.")
