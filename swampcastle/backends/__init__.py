"""Storage backend implementations for SwampCastle."""

import os

from .base import BaseCollection
from .lance import LanceBackend, LanceCollection

__all__ = [
    "BaseCollection",
    "LanceBackend",
    "LanceCollection",
    "detect_backend",
    "open_collection",
]


def detect_backend(palace_path: str) -> str:
    """Auto-detect storage backend from existing palace data.

    Returns "lance" for LanceDB palaces, "chroma" for ChromaDB palaces,
    or "lance" as default for new/empty directories.
    """
    if not os.path.isdir(palace_path):
        return "lance"

    for entry in os.listdir(palace_path):
        if entry.endswith(".lance"):
            return "lance"

    if os.path.exists(os.path.join(palace_path, "chroma.sqlite3")):
        return "chroma"

    return "lance"


def open_collection(
    palace_path: str,
    collection_name: str = "swampcastle_chests",
    backend: str = None,
    embedder=None,
    create: bool = True,
    sync_identity=None,
):
    """Open or create a palace collection.

    Args:
        palace_path: Path to the palace data directory.
        collection_name: Table/collection name.
        backend: "lance" or "chroma". Auto-detected if None.
        embedder: Embedder instance (required for lance, ignored for chroma).
        create: If True, create the palace directory if missing.
        sync_identity: NodeIdentity for sync metadata injection.
    """
    if backend is None:
        backend = detect_backend(palace_path)

    if create:
        os.makedirs(palace_path, exist_ok=True)
        try:
            os.chmod(palace_path, 0o700)
        except (OSError, NotImplementedError):
            pass

    if backend == "lance":
        from .lance import LanceBackend
        return LanceBackend().get_collection(
            palace_path, collection_name, create=create,
            embedder=embedder, sync_identity=sync_identity,
        )
    elif backend == "chroma":
        from .chroma import ChromaBackend
        return ChromaBackend().get_collection(
            palace_path, collection_name, create=create,
        )
    else:
        raise ValueError(f"Unknown backend: {backend}")
