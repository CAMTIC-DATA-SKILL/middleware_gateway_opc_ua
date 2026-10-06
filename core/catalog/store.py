from __future__ import annotations

import os
from pathlib import Path

import yaml

from core.catalog.model import Catalog


def load_catalog(path: Path) -> Catalog:
    """파일이 없으면 빈 카탈로그를 반환한다."""
    if not path.exists():
        return Catalog()
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Catalog.from_dict(data)


def save_catalog(catalog: Catalog, path: Path) -> None:
    """쓰는 도중 중단되어도 기존 카탈로그가 깨지지 않도록 임시 파일에 쓴 뒤 교체한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(catalog.to_dict(), f, allow_unicode=True, sort_keys=False)
    os.replace(tmp_path, path)
