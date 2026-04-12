"""ChromaDB-backed SwampCastle collection adapter (legacy)."""

import os

from .base import BaseCollection


class ChromaCollection(BaseCollection):
    """Thin adapter over a ChromaDB collection."""

    def __init__(self, collection):
        self._col = collection

    def add(self, *, documents, ids, metadatas=None):
        kwargs = {"documents": documents, "ids": ids}
        if metadatas is not None:
            kwargs["metadatas"] = metadatas
        return self._col.add(**kwargs)

    def upsert(self, *, documents, ids, metadatas=None):
        kwargs = {"documents": documents, "ids": ids}
        if metadatas is not None:
            kwargs["metadatas"] = metadatas
        return self._col.upsert(**kwargs)

    def get(self, *, ids=None, where=None, limit=None, offset=None, include=None):
        kwargs = {}
        if ids is not None:
            kwargs["ids"] = ids
        if where is not None:
            kwargs["where"] = where
        if limit is not None:
            kwargs["limit"] = limit
        if offset is not None:
            kwargs["offset"] = offset
        if include is not None:
            kwargs["include"] = include
        return self._col.get(**kwargs)

    def query(self, *, query_texts, n_results=5, where=None, include=None):
        kwargs = {"query_texts": query_texts, "n_results": n_results}
        if where:
            kwargs["where"] = where
        if include:
            kwargs["include"] = include
        return self._col.query(**kwargs)

    def delete(self, *, ids):
        return self._col.delete(ids=ids)

    def update(self, *, ids, documents=None, metadatas=None):
        kwargs = {"ids": ids}
        if documents is not None:
            kwargs["documents"] = documents
        if metadatas is not None:
            kwargs["metadatas"] = metadatas
        return self._col.update(**kwargs)

    def count(self):
        return self._col.count()


class ChromaBackend:
    """Factory for ChromaDB backend."""

    def get_collection(self, palace_path: str, collection_name: str, create: bool = False):
        try:
            import chromadb
        except ImportError:
            raise ImportError(
                "This palace uses the ChromaDB backend but 'chromadb' is not installed. "
                "Install with: pip install 'swampcastle[chroma]'  "
                "Or migrate to LanceDB with: swampcastle migrate"
            )

        if not create and not os.path.isdir(palace_path):
            raise FileNotFoundError(palace_path)

        if create:
            os.makedirs(palace_path, exist_ok=True)
            try:
                os.chmod(palace_path, 0o700)
            except (OSError, NotImplementedError):
                pass

        client = chromadb.PersistentClient(path=palace_path)
        if create:
            collection = client.get_or_create_collection(collection_name)
        else:
            collection = client.get_collection(collection_name)
        return ChromaCollection(collection)
