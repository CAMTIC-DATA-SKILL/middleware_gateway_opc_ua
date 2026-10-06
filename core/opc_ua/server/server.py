from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from asyncua import Node, Server, ua
from asyncua.common.instantiate_util import instantiate

from config import NorthboundConfig, config
from core.opc_ua.catalog import Catalog, CatalogTag, log_validation, validate_catalog
from core.opc_ua.catalog.types import NUMERIC_DATA_TYPES
from core.opc_ua.catalog.units import UNECE_NAMESPACE_URI, lookup_unit
from core.opc_ua.catalog.validation import RESERVED_NAME
from core.opc_ua.server.values import coerce_value
from utils.log_setup import get_logger

logger = get_logger(__name__)

_GOOD = ua.StatusCode(ua.StatusCodes.Good)
_WAITING = ua.StatusCode(ua.StatusCodes.BadWaitingForInitialData)
_TYPE_MISMATCH = ua.StatusCode(ua.StatusCodes.BadTypeMismatch)


@dataclass(frozen=True)
class _TagNode:
    node_id: ua.NodeId
    vtype: ua.VariantType
    source: str


@dataclass(frozen=True)
class _SourceStatus:
    connected: ua.NodeId
    last_update: ua.NodeId


class OpcUaServer:
    """
    카탈로그의 target 정보로 주소 공간을 구성하는 북향 OPC UA 서버.

    - 시작 시 카탈로그를 검증하고, 오류가 없는 `enabled: true` 태그만 노드로 만든다.
    - NodeId 를 `s=<target.path>`(객체), `s=<tag_id>`(변수)로 고정해 재시작해도 상위 시스템의 주소가 바뀌지 않는다.
    - 숫자 태그는 표준 아날로그 타입으로 만든다. eu_range 가 있으면 AnalogItemType, 없으면 BaseAnalogType.
    - 현장 값을 받기 전까지 StatusCode 는 BadWaitingForInitialData 로 둔다.
    - `_Gateway` 아래에 게이트웨이 상태 노드를 둔다.

        async with OpcUaServer(catalog) as server:
            await server.update("line01.temperature", 25.3, source_timestamp=ts)
    """

    def __init__(self, catalog: Catalog, cfg: NorthboundConfig | None = None) -> None:
        self._catalog = catalog
        self._cfg = cfg or config.northbound
        self._server: Server | None = None
        self._ns = 0
        self._objects: dict[tuple[str, ...], Node] = {}
        self._tags: dict[str, _TagNode] = {}
        self._sources: dict[str, _SourceStatus] = {}
        self._last_update: ua.NodeId | None = None
        self._last_values: dict[str, ua.Variant] = {}
        self._mismatch_logged: set[str] = set()

    async def __aenter__(self) -> OpcUaServer:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    @property
    def tag_ids(self) -> list[str]:
        return list(self._tags)

    @property
    def source_ids(self) -> list[str]:
        return list(self._sources)

    async def start(self) -> None:
        if self._server is not None:
            return

        cfg = self._cfg
        server = Server()
        await server.init()
        server.set_endpoint(cfg.endpoint)
        server.set_server_name(cfg.server_name)
        await server.set_application_uri(cfg.application_uri)
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        self._ns = await server.register_namespace(cfg.namespace_uri)
        self._objects = {(): server.nodes.objects}
        self._server = server

        try:
            validation = validate_catalog(self._catalog)
            log_validation(validation)
            invalid = validation.invalid_tag_ids
            for tag in self._catalog.tags:
                if tag.enabled and tag.tag_id not in invalid:
                    await self._add_tag(tag)
            await self._build_status_nodes(excluded_count=len(invalid))
            await server.start()
        except BaseException:
            self._server = None
            raise

        logger.info(
            "북향 OPC UA 서버 시작: %s (namespace=%s, 태그 %d개)",
            cfg.endpoint,
            cfg.namespace_uri,
            len(self._tags),
        )
        if not self._tags:
            logger.warning("제공할 태그가 없습니다. 카탈로그에서 태그를 enabled: true 로 바꿔 주세요.")

    async def stop(self) -> None:
        if self._server is None:
            return
        try:
            await self._server.stop()
        finally:
            self._server = None
            self._tags.clear()
            self._sources.clear()
            self._last_values.clear()
            logger.info("북향 OPC UA 서버 종료: %s", self._cfg.endpoint)

    async def update(
        self,
        tag_id: str,
        value: Any,
        status: ua.StatusCode | int | None = None,
        source_timestamp: datetime | None = None,
    ) -> bool:
        """
        태그 값을 갱신한다. 등록되지 않은 tag_id 면 False 를 반환한다.

        - value 가 None 이면 마지막으로 받은 정상 값을 유지하고 품질 상태만 바꾼다.
          (예: 연결 끊김 시 UncertainLastUsableValue). 아직 받은 값이 없으면 아무것도 바꾸지 않는다.
        - 품질이 Bad 이면 OPC UA 규격에 따라 값은 null 로 전달된다.
        - 노드의 데이터 형식으로 변환할 수 없으면 BadTypeMismatch 로 표시한다.
        - source_timestamp 가 없으면 게이트웨이 수신 시각을 발생 시각으로 쓴다.
        """
        tag = self._tags.get(tag_id)
        if tag is None or self._server is None:
            return False

        now = datetime.now(timezone.utc)
        status_code = ua.StatusCode(status) if isinstance(status, int) else (status or _GOOD)
        variant: ua.Variant | None = None

        if value is not None:
            try:
                variant = ua.Variant(coerce_value(value, tag.vtype), tag.vtype)
                self._mismatch_logged.discard(tag_id)
            except (TypeError, ValueError, OverflowError) as e:
                if tag_id not in self._mismatch_logged:
                    logger.warning("값을 %s 형식으로 변환할 수 없어 품질을 Bad 로 표시합니다: %s (%s)", tag.vtype.name, tag_id, e)
                    self._mismatch_logged.add(tag_id)
                status_code = _TYPE_MISMATCH

        if status_code.is_bad():
            variant = ua.Variant()
        elif variant is None:
            # 서버는 Bad 상태로 쓰면 값을 null 로 저장하므로, 마지막 값은 서버가 아닌 캐시에서 가져온다.
            variant = self._last_values.get(tag_id)
            if variant is None:
                return True
        else:
            self._last_values[tag_id] = variant

        written = await self._write(
            tag.node_id,
            ua.DataValue(variant, StatusCode=status_code, SourceTimestamp=source_timestamp or now, ServerTimestamp=now),
        )
        if not written:
            return True
        await self._write_status(self._last_update, now, ua.VariantType.DateTime)
        source = self._sources.get(tag.source)
        if source is not None:
            await self._write_status(source.last_update, now, ua.VariantType.DateTime)
        return True

    async def set_source_connected(self, server_id: str, connected: bool) -> bool:
        source = self._sources.get(server_id)
        if source is None or self._server is None:
            return False
        await self._write_status(source.connected, connected, ua.VariantType.Boolean)
        return True

    async def _ensure_object_path(self, segments: tuple[str, ...]) -> Node:
        for depth in range(1, len(segments) + 1):
            key = segments[:depth]
            if key not in self._objects:
                self._objects[key] = await self._objects[key[:-1]].add_object(
                    ua.NodeId("/".join(key), self._ns),
                    ua.QualifiedName(key[-1], self._ns),
                )
        return self._objects[segments]

    async def _add_tag(self, tag: CatalogTag) -> None:
        target = tag.target
        vtype = ua.VariantType[target.data_type]
        parent = await self._ensure_object_path(target.segments)
        node_id = ua.NodeId(tag.tag_id, self._ns)
        browse_name = ua.QualifiedName(target.name, self._ns)

        if target.data_type in NUMERIC_DATA_TYPES:
            variable = await self._add_analog_variable(parent, node_id, browse_name, tag, vtype)
        else:
            variable = await parent.add_variable(
                node_id, browse_name, ua.get_default_value(vtype), varianttype=vtype, datatype=_data_type_id(vtype)
            )

        description = tag.description or tag.name
        if description:
            await variable.write_attribute(
                ua.AttributeIds.Description,
                ua.DataValue(ua.Variant(ua.LocalizedText(description), ua.VariantType.LocalizedText)),
            )

        await variable.write_value(
            ua.DataValue(ua.Variant(ua.get_default_value(vtype), vtype), StatusCode=_WAITING)
        )
        self._tags[tag.tag_id] = _TagNode(node_id, vtype, tag.source.server)

    async def _add_analog_variable(
        self,
        parent: Node,
        node_id: ua.NodeId,
        browse_name: ua.QualifiedName,
        tag: CatalogTag,
        vtype: ua.VariantType,
    ) -> Node:
        assert self._server is not None
        target = tag.target
        type_id = ua.ObjectIds.AnalogItemType if target.eu_range else ua.ObjectIds.BaseAnalogType
        variable = (
            await instantiate(
                parent,
                self._server.get_node(ua.NodeId(type_id)),
                node_id,
                browse_name,
                idx=self._ns,
                instantiate_optional=False,
            )
        )[0]
        await variable.write_attribute(
            ua.AttributeIds.DataType, ua.DataValue(ua.Variant(_data_type_id(vtype), ua.VariantType.NodeId))
        )
        await variable.write_attribute(
            ua.AttributeIds.ValueRank, ua.DataValue(ua.Variant(int(ua.ValueRank.Scalar), ua.VariantType.Int32))
        )

        if target.eu_range:
            eu_range = await variable.get_child(ua.QualifiedName("EURange", 0))
            await eu_range.write_value(
                ua.Variant(ua.Range(Low=float(target.eu_range.low), High=float(target.eu_range.high)), ua.VariantType.ExtensionObject)
            )

        if target.unit:
            await variable.add_property(
                ua.NodeId(f"{tag.tag_id}.EngineeringUnits", self._ns),
                ua.QualifiedName("EngineeringUnits", 0),
                _eu_information(target.unit),
                varianttype=ua.VariantType.ExtensionObject,
                datatype=ua.NodeId(ua.ObjectIds.EUInformation),
            )
        return variable

    async def _build_status_nodes(self, excluded_count: int) -> None:
        objects = self._objects[()]
        root = await objects.add_object(ua.NodeId(RESERVED_NAME, self._ns), ua.QualifiedName(RESERVED_NAME, self._ns))
        now = datetime.now(timezone.utc)

        await self._add_status_variable(root, "StartTime", now, ua.VariantType.DateTime, "게이트웨이 서버 시작 시각")
        await self._add_status_variable(root, "TagCount", len(self._tags), ua.VariantType.UInt32, "제공 중인 태그 수")
        await self._add_status_variable(
            root, "ExcludedTagCount", excluded_count, ua.VariantType.UInt32, "카탈로그 검증 오류로 제외된 태그 수"
        )
        self._last_update = await self._add_status_variable(
            root, "LastUpdateTime", None, ua.VariantType.DateTime, "마지막으로 태그 값을 갱신한 시각"
        )

        sources_node = await root.add_object(
            ua.NodeId(f"{RESERVED_NAME}.Sources", self._ns), ua.QualifiedName("Sources", self._ns)
        )
        for source in sorted({tag.source for tag in self._tags.values()}):
            node = await sources_node.add_object(
                ua.NodeId(f"{RESERVED_NAME}.Sources.{source}", self._ns), ua.QualifiedName(source, self._ns)
            )
            self._sources[source] = _SourceStatus(
                connected=await self._add_status_variable(
                    node, "Connected", False, ua.VariantType.Boolean, "현장 서버 연결 여부"
                ),
                last_update=await self._add_status_variable(
                    node, "LastUpdateTime", None, ua.VariantType.DateTime, "이 현장 서버의 태그 값을 마지막으로 갱신한 시각"
                ),
            )

    async def _add_status_variable(
        self,
        parent: Node,
        name: str,
        value: Any,
        vtype: ua.VariantType,
        description: str,
    ) -> ua.NodeId:
        """value 가 None 이면 아직 값이 없다는 뜻으로 BadWaitingForInitialData 상태로 만든다."""
        parent_id = parent.nodeid.Identifier
        variable = await parent.add_variable(
            ua.NodeId(f"{parent_id}.{name}", self._ns),
            ua.QualifiedName(name, self._ns),
            ua.get_default_value(vtype) if value is None else value,
            varianttype=vtype,
            datatype=_data_type_id(vtype),
        )
        await variable.write_attribute(
            ua.AttributeIds.Description,
            ua.DataValue(ua.Variant(ua.LocalizedText(description), ua.VariantType.LocalizedText)),
        )
        if value is None:
            await variable.write_value(ua.DataValue(ua.Variant(ua.get_default_value(vtype), vtype), StatusCode=_WAITING))
        return variable.nodeid

    async def _write_status(self, node_id: ua.NodeId | None, value: Any, vtype: ua.VariantType) -> None:
        if node_id is not None:
            await self._write(node_id, ua.DataValue(ua.Variant(value, vtype), StatusCode=_GOOD))

    async def _write(self, node_id: ua.NodeId, data_value: ua.DataValue) -> bool:
        """`Server.write_attribute_value` 는 쓰기 실패 결과를 버리므로, 주소 공간에 직접 써서 결과를 확인한다."""
        if self._server is None:
            return False
        result = await self._server.iserver.aspace.write_attribute_value(node_id, ua.AttributeIds.Value, data_value)
        if not result.is_good():
            logger.warning("노드 값 쓰기 실패: %s (%s)", node_id.to_string(), result.name)
            return False
        return True


def _data_type_id(vtype: ua.VariantType) -> ua.NodeId:
    return ua.NodeId(getattr(ua.ObjectIds, vtype.name))


def _eu_information(unit: str) -> ua.EUInformation:
    info = lookup_unit(unit)
    if info is None:
        return ua.EUInformation(
            NamespaceUri=UNECE_NAMESPACE_URI,
            UnitId=-1,
            DisplayName=ua.LocalizedText(unit),
            Description=ua.LocalizedText(unit),
        )
    return ua.EUInformation(
        NamespaceUri=UNECE_NAMESPACE_URI,
        UnitId=info.unit_id,
        DisplayName=ua.LocalizedText(info.symbol),
        Description=ua.LocalizedText(info.description),
    )
