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
    """Contract for knowledge graph backends (SQLite, Postgres, in-memory).

    Accepted facts live in the main entity/triple tables.
    Proposed extracted facts live in a separate candidate-triple store so KG
    queries remain trustworthy until proposals are explicitly reviewed.
    """

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
    def propose_triple(
        self,
        *,
        subject_text: str,
        predicate: str,
        object_text: str,
        confidence: float,
        modality: str,
        polarity: str,
        evidence_drawer_id: str,
        evidence_text: str,
        extractor_version: str,
        valid_from: str | None = None,
        valid_to: str | None = None,
        source_file: str | None = None,
        wing: str | None = None,
        room: str | None = None,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_candidate_triple(self, *, candidate_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def list_candidate_triples(
        self,
        *,
        status: str | None = None,
        predicate: str | None = None,
        min_confidence: float | None = None,
        wing: str | None = None,
        room: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def set_candidate_status(
        self,
        *,
        candidate_id: str,
        status: str,
        reviewed_at: str | None = None,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
