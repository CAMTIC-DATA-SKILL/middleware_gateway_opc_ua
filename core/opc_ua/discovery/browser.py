from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from asyncua import Client, ua

from utils.log_setup import get_logger

logger = get_logger(__name__)

BROWSE_CHUNK_SIZE = 100
READ_CHUNK_SIZE = 500

_OBJECTS_FOLDER = ua.NodeId(ua.ObjectIds.ObjectsFolder)
_HAS_PROPERTY = ua.NodeId(ua.ObjectIds.HasProperty)
_ENGINEERING_UNITS = ua.QualifiedName("EngineeringUnits", 0)
_EU_RANGE = ua.QualifiedName("EURange", 0)


@dataclass(frozen=True)
class DiscoveredVariable:
    node_id: ua.NodeId
    namespace_uri: str
    identifier: str
    browse_path: tuple[str, ...]
    display_name: str
    description: str
    data_type: str
    unit: str
    eu_range: tuple[float, float] | None


@dataclass
class BrowseResult:
    variables: list[DiscoveredVariable]
    visited_count: int
    truncated: bool


@dataclass
class _Pending:
    node_id: ua.NodeId
    node_class: ua.NodeClass
    path: tuple[str, ...]
    depth: int
    display_name: str = ""
    eu_node: ua.NodeId | None = field(default=None)
    eu_range_node: ua.NodeId | None = field(default=None)


def _chunks(items: Sequence, size: int) -> Iterator[Sequence]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def split_node_id(node_id: ua.NodeId) -> str:
    """`ns=2;s=A.B` 에서 네임스페이스 번호를 뗀 `s=A.B` 부분을 반환한다."""
    text = node_id.to_string()
    if text.startswith("ns="):
        return text.split(";", 1)[1]
    return text


class AddressSpaceBrowser:
    """
    현장 서버의 주소 공간을 탐색해 Variable 노드 목록을 수집한다.

    - 계층 참조(HierarchicalReferences)만 따라가며, 방문한 노드는 다시 탐색하지 않는다.
    - 같은 깊이의 노드를 묶어 한 번의 Browse 요청으로 처리한다.
    - 표준 네임스페이스(ns=0) 노드(Server 객체 등)는 장비 데이터가 아니므로 제외한다.
    - Property(HasProperty)는 태그로 수집하지 않고, EngineeringUnits 만 단위 정보로 사용한다.
    """

    def __init__(self, client: Client, max_depth: int = 10, max_nodes: int = 50_000) -> None:
        self._client = client
        self._ua = client.uaclient
        self._max_depth = max_depth
        self._max_nodes = max_nodes
        self._namespaces: list[str] = []

    async def browse(self, root: ua.NodeId | None = None) -> BrowseResult:
        self._namespaces = await self._client.get_namespace_array()
        root_id = root or _OBJECTS_FOLDER
        root_path = await self._path_from_objects(root_id) if root_id != _OBJECTS_FOLDER else ()

        frontier = [_Pending(root_id, ua.NodeClass.Object, root_path, 0)]
        visited: set[ua.NodeId] = {root_id}
        variables: list[_Pending] = []
        truncated = False

        while frontier and not truncated:
            next_frontier: list[_Pending] = []
            references = await self._browse_many([p.node_id for p in frontier])

            for parent, refs in zip(frontier, references):
                if truncated:
                    break
                for ref in refs:
                    child_id = self._to_local_node_id(ref.NodeId)
                    if child_id is None or child_id.NamespaceIndex == 0:
                        continue

                    if ref.ReferenceTypeId == _HAS_PROPERTY:
                        if parent.node_class == ua.NodeClass.Variable:
                            if ref.BrowseName == _ENGINEERING_UNITS:
                                parent.eu_node = child_id
                            elif ref.BrowseName == _EU_RANGE:
                                parent.eu_range_node = child_id
                        continue

                    if child_id in visited:
                        continue
                    if len(visited) >= self._max_nodes:
                        truncated = True
                        break
                    visited.add(child_id)

                    child = _Pending(
                        node_id=child_id,
                        node_class=ref.NodeClass,
                        path=parent.path + (ref.BrowseName.Name,),
                        depth=parent.depth + 1,
                        display_name=ref.DisplayName.Text or ref.BrowseName.Name,
                    )
                    if child.node_class == ua.NodeClass.Variable:
                        variables.append(child)
                    if child.depth < self._max_depth:
                        next_frontier.append(child)

            frontier = next_frontier

        if truncated:
            logger.warning("탐색 노드 수가 상한(%d)에 도달해 탐색을 중단했습니다.", self._max_nodes)

        return BrowseResult(
            variables=await self._describe(variables),
            visited_count=len(visited) - 1,
            truncated=truncated,
        )

    async def _path_from_objects(self, node_id: ua.NodeId) -> tuple[str, ...]:
        """
        Objects 폴더에서 node_id 까지의 BrowseName 경로를 구한다.

        --root 로 일부만 탐색해도 전체 탐색과 같은 browse_path 가 나와야 카탈로그와 비교할 수 있다.
        상위 참조에도 순환이 있을 수 있으므로 위쪽으로 너비 우선 탐색해 최단 경로를 사용한다.
        """
        browse_name = (await self._read_many([node_id], ua.AttributeIds.BrowseName))[0]
        if not isinstance(browse_name, ua.QualifiedName):
            raise ValueError(f"탐색 시작 노드를 찾을 수 없습니다: {node_id.to_string()}")

        frontier: list[tuple[ua.NodeId, tuple[str, ...]]] = [(node_id, (browse_name.Name,))]
        visited = {node_id}
        while frontier:
            next_frontier = []
            parents = await self._browse_many([n for n, _ in frontier], ua.BrowseDirection.Inverse)
            for (_, path), refs in zip(frontier, parents):
                for ref in refs:
                    parent_id = self._to_local_node_id(ref.NodeId)
                    if parent_id is None or parent_id in visited:
                        continue
                    if parent_id == _OBJECTS_FOLDER:
                        return path
                    visited.add(parent_id)
                    next_frontier.append((parent_id, (ref.BrowseName.Name, *path)))
            frontier = next_frontier

        raise ValueError(f"탐색 시작 노드가 Objects 폴더 하위에 있지 않습니다: {node_id.to_string()}")

    def _to_local_node_id(self, node_id: ua.NodeId | ua.ExpandedNodeId) -> ua.NodeId | None:
        """asyncua 는 서버 인덱스나 URI 가 없는 참조 대상을 ExpandedNodeId 가 아닌 NodeId 로 디코딩한다."""
        if getattr(node_id, "ServerIndex", 0):
            return None
        index = node_id.NamespaceIndex
        namespace_uri = getattr(node_id, "NamespaceUri", None)
        if namespace_uri:
            if namespace_uri not in self._namespaces:
                return None
            index = self._namespaces.index(namespace_uri)
        return ua.NodeId(node_id.Identifier, index, node_id.NodeIdType)

    async def _browse_many(
        self,
        node_ids: Sequence[ua.NodeId],
        direction: ua.BrowseDirection = ua.BrowseDirection.Forward,
    ) -> list[list[ua.ReferenceDescription]]:
        results: list[list[ua.ReferenceDescription]] = []
        for chunk in _chunks(node_ids, BROWSE_CHUNK_SIZE):
            params = ua.BrowseParameters()
            params.RequestedMaxReferencesPerNode = 0
            params.NodesToBrowse = [
                ua.BrowseDescription(
                    NodeId=node_id,
                    BrowseDirection=direction,
                    ReferenceTypeId=ua.NodeId(ua.ObjectIds.HierarchicalReferences),
                    IncludeSubtypes=True,
                    NodeClassMask=ua.NodeClass.Object | ua.NodeClass.Variable,
                    ResultMask=ua.BrowseResultMask.All,
                )
                for node_id in chunk
            ]

            for node_id, result in zip(chunk, await self._ua.browse(params)):
                if not result.StatusCode.is_good():
                    logger.warning("노드 탐색 실패: %s (%s)", node_id.to_string(), result.StatusCode.name)
                    results.append([])
                    continue

                refs = list(result.References or [])
                continuation = result.ContinuationPoint
                while continuation:
                    next_params = ua.BrowseNextParameters(
                        ReleaseContinuationPoints=False,
                        ContinuationPoints=[continuation],
                    )
                    next_result = (await self._ua.browse_next(next_params))[0]
                    refs.extend(next_result.References or [])
                    continuation = next_result.ContinuationPoint
                results.append(refs)
        return results

    async def _read_many(self, node_ids: Sequence[ua.NodeId], attribute: ua.AttributeIds) -> list[object]:
        values: list[object] = []
        for chunk in _chunks(node_ids, READ_CHUNK_SIZE):
            params = ua.ReadParameters()
            params.TimestampsToReturn = ua.TimestampsToReturn.Neither
            params.NodesToRead = [ua.ReadValueId(NodeId=node_id, AttributeId=attribute) for node_id in chunk]
            for data_value in await self._ua.read(params):
                good = data_value.StatusCode is None or data_value.StatusCode.is_good()
                values.append(data_value.Value.Value if good and data_value.Value else None)
        return values

    async def _describe(self, pending: list[_Pending]) -> list[DiscoveredVariable]:
        if not pending:
            return []

        node_ids = [p.node_id for p in pending]
        data_type_ids = await self._read_many(node_ids, ua.AttributeIds.DataType)
        descriptions = await self._read_many(node_ids, ua.AttributeIds.Description)
        type_names = await self._resolve_type_names([t for t in data_type_ids if isinstance(t, ua.NodeId)])
        units = await self._read_units([p.eu_node for p in pending if p.eu_node is not None])
        ranges = await self._read_ranges([p.eu_range_node for p in pending if p.eu_range_node is not None])

        variables = []
        for item, data_type_id, description in zip(pending, data_type_ids, descriptions):
            variables.append(
                DiscoveredVariable(
                    node_id=item.node_id,
                    namespace_uri=self._namespaces[item.node_id.NamespaceIndex],
                    identifier=split_node_id(item.node_id),
                    browse_path=item.path,
                    display_name=item.display_name,
                    description=description.Text if isinstance(description, ua.LocalizedText) and description.Text else "",
                    data_type=type_names.get(data_type_id, "") if isinstance(data_type_id, ua.NodeId) else "",
                    unit=units.get(item.eu_node, "") if item.eu_node is not None else "",
                    eu_range=ranges.get(item.eu_range_node) if item.eu_range_node is not None else None,
                )
            )
        return variables

    async def _resolve_type_names(self, type_ids: list[ua.NodeId]) -> dict[ua.NodeId, str]:
        names: dict[ua.NodeId, str] = {}
        custom: list[ua.NodeId] = []
        for type_id in set(type_ids):
            if type_id.NamespaceIndex == 0 and type_id.Identifier in ua.ObjectIdNames:
                names[type_id] = ua.ObjectIdNames[type_id.Identifier]
            else:
                custom.append(type_id)

        for type_id, browse_name in zip(custom, await self._read_many(custom, ua.AttributeIds.BrowseName)):
            names[type_id] = browse_name.Name if isinstance(browse_name, ua.QualifiedName) else type_id.to_string()
        return names

    async def _read_units(self, eu_nodes: list[ua.NodeId]) -> dict[ua.NodeId, str]:
        units: dict[ua.NodeId, str] = {}
        for eu_node, value in zip(eu_nodes, await self._read_many(eu_nodes, ua.AttributeIds.Value)):
            if isinstance(value, ua.EUInformation) and value.DisplayName and value.DisplayName.Text:
                units[eu_node] = value.DisplayName.Text
        return units

    async def _read_ranges(self, range_nodes: list[ua.NodeId]) -> dict[ua.NodeId, tuple[float, float]]:
        ranges: dict[ua.NodeId, tuple[float, float]] = {}
        for range_node, value in zip(range_nodes, await self._read_many(range_nodes, ua.AttributeIds.Value)):
            if isinstance(value, ua.Range) and value.Low < value.High:
                ranges[range_node] = (value.Low, value.High)
        return ranges
