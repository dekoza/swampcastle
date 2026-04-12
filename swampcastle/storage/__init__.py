"""Storage layer for SwampCastle.

Provides StorageFactory ABC and backend detection.
"""

import os
from abc import ABC, abstractmethod

from .base import CollectionStore, GraphStore

__all__ = [
    "CollectionStore",
    "GraphStore",
    "StorageFactory",
    "detect_backend",
]


class StorageFactory(ABC):
    """Creates storage backends for a Castle instance."""

    @abstractmethod
    def open_collection(self, name: str) -> CollectionStore:
        raise NotImplementedError

    @abstractmethod
    def open_graph(self) -> GraphStore:
        raise NotImplementedError

    def close(self) -> None:
        pass


def detect_backend(castle_path: str) -> str:
    """Auto-detect storage backend from existing data.

    Returns "lance", "chroma", or "lance" (default for new/empty).
    """
    if not os.path.isdir(castle_path):
        return "lance"

    for entry in os.listdir(castle_path):
        if entry.endswith(".lance"):
            return "lance"

    if os.path.exists(os.path.join(castle_path, "chroma.sqlite3")):
        return "chroma"

    return "lance"
