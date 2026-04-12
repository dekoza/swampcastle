"""Abstract collection interface for SwampCastle storage backends."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseCollection(ABC):
    """Contract that every storage backend must implement."""

    @abstractmethod
    def add(
        self,
        *,
        documents: List[str],
        ids: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def upsert(
        self,
        *,
        documents: List[str],
        ids: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def query(
        self,
        *,
        query_texts: List[str],
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
        include: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get(
        self,
        *,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        include: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def delete(self, *, ids: List[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def update(
        self,
        *,
        ids: List[str],
        documents: Optional[List[str]] = None,
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def count(self) -> int:
        raise NotImplementedError
