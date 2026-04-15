"""Storage layer for SwampCastle.

Provides StorageFactory ABC, backend detection, and settings-based routing.
"""

import os
from abc import ABC, abstractmethod
from importlib import import_module

from swampcastle.embeddings import get_embedder
from swampcastle.settings import CastleSettings

from .base import CollectionStore, GraphStore

__all__ = [
    "CollectionStore",
    "GraphStore",
    "StorageFactory",
    "detect_backend",
    "factory_from_settings",
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


def _embedder_config_from_settings(settings) -> dict:
    config = getattr(settings, "embedder_config", None)
    if config is not None:
        return config

    embedder = getattr(settings, "embedder", "onnx")
    options = {}
    device = getattr(settings, "embedder_device", None)
    if device:
        options["device"] = device
    return (
        {"embedder": embedder, "embedder_options": options} if options else {"embedder": embedder}
    )


def factory_from_settings(settings: CastleSettings) -> StorageFactory:
    """Create the configured storage factory for a Castle instance."""
    if settings.backend == "lance":
        from .lance import LocalStorageFactory

        embedder = get_embedder(_embedder_config_from_settings(settings))
        return LocalStorageFactory(settings.castle_path, embedder=embedder)

    if settings.backend == "postgres":
        if not settings.database_url:
            raise ValueError("SWAMPCASTLE_DATABASE_URL required for postgres backend")
        try:
            module = import_module("swampcastle.storage.postgres")
        except ImportError as exc:
            raise ImportError(
                "PostgreSQL backend requires optional dependencies. "
                "Install with: pip install 'swampcastle[postgres]'"
            ) from exc
        embedder = get_embedder(_embedder_config_from_settings(settings))
        return module.PostgresStorageFactory(settings.database_url, embedder=embedder)

    if settings.backend == "chroma":
        raise NotImplementedError(
            "ChromaDB backend removed in v4; use 'swampcastle raise' to convert"
        )

    raise ValueError(f"Unknown backend: {settings.backend}")
