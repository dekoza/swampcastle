"""Abstract storage contracts for SwampCastle.

Two ABCs:
  CollectionStore — document + vector storage (drawers)
  GraphStore — entity-relationship graph (knowledge graph)
"""

from abc import ABC, abstractmethod
from typing import Any


class CollectionStore(ABC):
    """Contract for drawer storage backends (LanceDB, Postgres, in-memory)."""

    @abstractmethod
    def add(
        self,
        *,
        documents: list[str],
        ids: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def upsert(
        self,
        *,
        documents: list[str],
        ids: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def query(
        self,
        *,
        query_texts: list[str],
        n_results: int = 5,
        where: dict[str, Any] | None = None,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get(
        self,
        *,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def delete(self, *, ids: list[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def update(
        self,
        *,
        ids: list[str],
        documents: list[str] | None = None,
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def count(self) -> int:
        raise NotImplementedError


class GraphStore(ABC):
    """Contract for knowledge graph backends (SQLite, Postgres, in-memory)."""

    @abstractmethod
    def add_entity(
        self,
        *,
        name: str,
        entity_type: str = "unknown",
        properties: dict[str, Any] | None = None,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    def add_triple(
        self,
        *,
        subject: str,
        predicate: str,
        obj: str,
        valid_from: str | None = None,
        valid_to: str | None = None,
        confidence: float = 1.0,
        source_closet: str | None = None,
        source_file: str | None = None,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    def query_entity(
        self,
        *,
        name: str,
        as_of: str | None = None,
        direction: str = "outgoing",
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def query_relationship(
        self,
        *,
        predicate: str,
        as_of: str | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def invalidate(
        self,
        *,
        subject: str,
        predicate: str,
        obj: str,
        ended: str | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def timeline(
        self,
        *,
        entity_name: str | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def stats(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
