"""Castle — the central context object that wires everything together.

Usage:
    with Castle(settings, factory) as castle:
        castle.vault.add_drawer(...)
        castle.search.search(...)

AsyncCastle wraps a sync Castle for async surfaces (FastAPI, future async MCP).
"""

import anyio

from swampcastle.models.catalog import StatusResponse
from swampcastle.models.drawer import SearchQuery, SearchResponse
from swampcastle.services.catalog import CatalogService
from swampcastle.services.graph import GraphService
from swampcastle.services.search import SearchService
from swampcastle.services.vault import VaultService
from swampcastle.settings import CastleSettings
from swampcastle.storage import StorageFactory
from swampcastle.wal import WalWriter


class Castle:
    """Sync castle context. Owns all services and their dependencies."""

    def __init__(self, settings: CastleSettings, factory: StorageFactory):
        self._settings = settings
        self._factory = factory
        self._collection = factory.open_collection(settings.collection_name)
        self._graph_store = factory.open_graph()

        wal = WalWriter(settings.wal_path)

        self.catalog = CatalogService(self._collection, str(settings.castle_path))
        self.search = SearchService(self._collection)
        self.vault = VaultService(self._collection, wal)
        self.graph = GraphService(self._graph_store, self._collection, wal)

    @property
    def settings(self) -> CastleSettings:
        return self._settings

    def close(self):
        self._graph_store.close()
        self._factory.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class AsyncCastle:
    """Async wrapper. Delegates to sync Castle in a thread pool."""

    def __init__(self, castle: Castle):
        self._castle = castle

    async def search(self, query: SearchQuery) -> SearchResponse:
        return await anyio.to_thread.run_sync(
            lambda: self._castle.search.search(query)
        )

    async def status(self) -> StatusResponse:
        return await anyio.to_thread.run_sync(
            lambda: self._castle.catalog.status()
        )
