from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class CatalogError(ValueError):
    pass


class TagStatus(str, Enum):
    CANDIDATE = "candidate"
    APPROVED = "approved"
    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass
class SourceSpec:
    server: str
    namespace_uri: str
    identifier: str
    browse_path: str = ""
    data_type: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        """NodeId 의 네임스페이스 번호는 바뀔 수 있으므로 URI 기준으로 노드를 식별한다."""
        return (self.server, self.namespace_uri, self.identifier)


@dataclass
class EuRange:
    """정상 운전 시 값이 움직이는 범위. 상위 시스템의 트렌드 축, 게이지 범위 등에 쓰인다."""

    low: float
    high: float


@dataclass
class TargetSpec:
    path: str
    name: str
    data_type: str = ""
    unit: str = ""
    eu_range: EuRange | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TargetSpec:
        eu_range = data.get("eu_range")
        return cls(**{**data, "eu_range": EuRange(**eu_range) if eu_range else None})

    @property
    def segments(self) -> tuple[str, ...]:
        """`a//b/` 같은 표기도 `a/b` 와 같은 경로로 취급한다."""
        return tuple(segment for segment in self.path.split("/") if segment)


@dataclass
class CollectionSpec:
    sampling_interval_ms: int = 1000
    publishing_interval_ms: int = 1000
    deadband: float = 0.0


@dataclass
class ConversionSpec:
    scale: float = 1.0
    offset: float = 0.0


@dataclass
class CatalogTag:
    tag_id: str
    name: str
    source: SourceSpec
    target: TargetSpec
    description: str = ""
    enabled: bool = False
    status: TagStatus = TagStatus.CANDIDATE
    collection: CollectionSpec = field(default_factory=CollectionSpec)
    conversion: ConversionSpec = field(default_factory=ConversionSpec)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CatalogTag:
        return cls(
            tag_id=data["tag_id"],
            name=data.get("name", ""),
            description=data.get("description") or "",
            enabled=bool(data.get("enabled", False)),
            status=TagStatus(data.get("status", TagStatus.CANDIDATE.value)),
            source=SourceSpec(**data["source"]),
            target=TargetSpec.from_dict(data["target"]),
            collection=CollectionSpec(**(data.get("collection") or {})),
            conversion=ConversionSpec(**(data.get("conversion") or {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag_id": self.tag_id,
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "status": self.status.value,
            "source": asdict(self.source),
            "target": asdict(self.target),
            "collection": asdict(self.collection),
            "conversion": asdict(self.conversion),
        }


@dataclass
class Catalog:
    tags: list[CatalogTag] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Catalog:
        tags: list[CatalogTag] = []
        seen: set[str] = set()
        for index, item in enumerate(data.get("tags") or [], start=1):
            try:
                tag = CatalogTag.from_dict(item)
            except (KeyError, TypeError, ValueError) as e:
                tag_id = item.get("tag_id", "?") if isinstance(item, dict) else "?"
                reason = f"필수 항목 {e} 이(가) 없습니다." if isinstance(e, KeyError) else str(e)
                raise CatalogError(f"{index}번째 태그({tag_id})를 읽을 수 없습니다: {reason}") from e
            if tag.tag_id in seen:
                raise CatalogError(f"카탈로그에 중복된 tag_id 가 있습니다: {tag.tag_id}")
            seen.add(tag.tag_id)
            tags.append(tag)
        return cls(tags=tags)

    def to_dict(self) -> dict[str, Any]:
        return {"tags": [tag.to_dict() for tag in self.tags]}

    @property
    def tag_ids(self) -> set[str]:
        return {tag.tag_id for tag in self.tags}

    def by_source_key(self) -> dict[tuple[str, str, str], CatalogTag]:
        return {tag.source.key: tag for tag in self.tags}
