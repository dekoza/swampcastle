"""Internal source-adapter contract for SwampCastle mining."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from swampcastle.models.origin import SourceOrigin


@dataclass(frozen=True)
class SourceItem:
    path: Path


@dataclass(frozen=True)
class ProjectSourceItem(SourceItem):
    """One project file discovered for ingest."""


@dataclass(frozen=True)
class ConversationSourceItem(SourceItem):
    """One conversation transcript discovered for ingest."""


@dataclass(frozen=True)
class ProjectSourceResult:
    drawers: int
    room: str | None


@dataclass(frozen=True)
class ConversationSourceResult:
    filepath: Path
    chunks: list[dict[str, Any]]
    room: str | None
    contributor: str | None
    origin: SourceOrigin
    source_mtime: int | None


class BaseSourceAdapter(ABC):
    """Internal contract for source discovery + per-item ingest preparation."""

    name: str
    declared_transformations: tuple[str, ...] = ()

    def __init__(self, source_path: str | Path):
        self.source_path = Path(source_path).expanduser().resolve()

    @abstractmethod
    def scan(self, *, limit: int = 0) -> list[SourceItem]:
        raise NotImplementedError

    @abstractmethod
    def ingest(self, item: SourceItem, **kwargs):
        raise NotImplementedError
