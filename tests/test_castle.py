"""Tests for swampcastle.castle — Castle context + AsyncCastle wrapper."""

import pytest

from swampcastle.castle import AsyncCastle, Castle
from swampcastle.models import AddDrawerCommand, SearchQuery
from swampcastle.settings import CastleSettings
from swampcastle.storage.memory import InMemoryStorageFactory


@pytest.fixture
def settings(tmp_path):
    return CastleSettings(castle_path=tmp_path / "castle", _env_file=None)


@pytest.fixture
def factory():
    return InMemoryStorageFactory()


@pytest.fixture
def castle(settings, factory):
    with Castle(settings, factory) as c:
        yield c


class TestCastleLifecycle:
    def test_context_manager(self, settings, factory):
        with Castle(settings, factory) as c:
            assert c.catalog is not None
            assert c.audit is not None
            assert c.search is not None
            assert c.vault is not None
            assert c.graph is not None
            assert c.kg_proposals is not None

    def test_skip_embedder_check_propagated_to_factory(self, settings, factory, monkeypatch):
        calls = []
        real_open = factory.open_collection

        def spy_open_collection(name, *, skip_embedder_check=False):
            calls.append(skip_embedder_check)
            return real_open(name)

        monkeypatch.setattr(factory, "open_collection", spy_open_collection)

        Castle(settings, factory, skip_embedder_check=True)
        assert calls == [True]

        Castle(settings, factory, skip_embedder_check=False)
        assert calls == [True, False]

        Castle(settings, factory)
        assert calls == [True, False, False]

    def test_services_accessible(self, castle):
        assert castle.catalog is not None
        assert castle.audit is not None
        assert castle.search is not None
        assert castle.vault is not None
        assert castle.graph is not None
        assert castle.kg_proposals is not None

    def test_close_callable(self, settings, factory):
        c = Castle(settings, factory)
        c.close()


class TestCastleRoundtrip:
    def test_add_then_search(self, castle):
        castle.vault.add_drawer(
            AddDrawerCommand(wing="test", room="arch", content="chose postgres for scaling")
        )
        result = castle.search.search(SearchQuery(query="postgres scaling"))
        assert len(result.results) > 0
        assert "postgres" in result.results[0].text.lower()

    def test_add_then_status(self, castle):
        from swampcastle.services.digest import build_digest

        castle.vault.add_drawer(AddDrawerCommand(wing="proj", room="auth", content="jwt decision"))
        status = build_digest(castle)
        assert "1 drawers" in status.digest
        assert "proj" in status.digest

    def test_kg_roundtrip(self, castle):
        castle.graph.kg_add(
            subject="Kai",
            predicate="works_on",
            obj="Orion",
        )
        result = castle.graph.kg_query(entity="Kai")
        assert result.count == 1

    def test_vault_write_invalidates_graph_cache(self, castle):
        """Vault write must invalidate the palace graph so the next query rebuilds it."""
        castle.vault.add_drawer(AddDrawerCommand(wing="proj", room="auth", content="a"))
        castle.graph.traverse("auth")
        graph_id_1 = id(castle.graph._palace_graph)

        # Second read uses cached PalaceGraph
        castle.graph.traverse("auth")
        assert id(castle.graph._palace_graph) == graph_id_1

        # Vault write invalidates the cache
        castle.vault.add_drawer(AddDrawerCommand(wing="personal", room="auth", content="b"))
        assert castle.graph._palace_graph is None, "Cache should be cleared after vault write"

        # Next query rebuilds
        castle.graph.traverse("auth")
        assert castle.graph._palace_graph is not None
        assert id(castle.graph._palace_graph) != graph_id_1, "New PalaceGraph instance after invalidation"


class TestAsyncCastle:
    @pytest.fixture
    def async_castle(self, castle):
        return AsyncCastle(castle)

    def test_search(self, castle, async_castle):
        import anyio

        castle.vault.add_drawer(
            AddDrawerCommand(wing="test", room="r", content="async test content")
        )

        async def _search():
            return await async_castle.search(SearchQuery(query="async test"))

        result = anyio.from_thread.run(_search) if False else anyio.run(_search)
        assert len(result.results) > 0

    def test_status(self, async_castle):
        import anyio

        async def _status():
            return await async_castle.status()

        result = anyio.run(_status)
        assert "0 drawers" in result.digest
