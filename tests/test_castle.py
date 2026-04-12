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
            assert c.search is not None
            assert c.vault is not None
            assert c.graph is not None

    def test_services_accessible(self, castle):
        assert castle.catalog is not None
        assert castle.search is not None
        assert castle.vault is not None
        assert castle.graph is not None

    def test_close_callable(self, settings, factory):
        c = Castle(settings, factory)
        c.close()


class TestCastleRoundtrip:
    def test_add_then_search(self, castle):
        castle.vault.add_drawer(
            AddDrawerCommand(wing="test", room="arch", content="chose postgres for scaling")
        )
        result = castle.search.search(
            SearchQuery(query="postgres scaling")
        )
        assert len(result.results) > 0
        assert "postgres" in result.results[0].text.lower()

    def test_add_then_status(self, castle):
        castle.vault.add_drawer(
            AddDrawerCommand(wing="proj", room="auth", content="jwt decision")
        )
        status = castle.catalog.status()
        assert status.total_drawers == 1
        assert "proj" in status.wings

    def test_kg_roundtrip(self, castle):
        castle.graph.kg_add(
            subject="Kai", predicate="works_on", obj="Orion",
        )
        result = castle.graph.kg_query(entity="Kai")
        assert result.count == 1


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
        assert result.total_drawers == 0
