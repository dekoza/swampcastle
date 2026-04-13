"""Integration test — Castle with real LanceDB + SQLite backends."""

import pytest

from swampcastle.castle import Castle
from swampcastle.models import AddDrawerCommand, SearchQuery
from swampcastle.settings import CastleSettings
from swampcastle.storage.lance import LocalStorageFactory


@pytest.mark.integration
class TestCastleIntegration:
    @pytest.fixture
    def castle(self, tmp_path):
        settings = CastleSettings(castle_path=tmp_path / "castle", _env_file=None)
        factory = LocalStorageFactory(settings.castle_path)
        with Castle(settings, factory) as c:
            yield c

    def test_add_and_search(self, castle):
        castle.vault.add_drawer(
            AddDrawerCommand(
                wing="proj", room="arch", content="chose postgres for horizontal scaling"
            )
        )
        r = castle.search.search(SearchQuery(query="postgres scaling"))
        assert len(r.results) > 0
        assert "postgres" in r.results[0].text.lower()

    def test_status_after_add(self, castle):
        castle.vault.add_drawer(
            AddDrawerCommand(wing="proj", room="auth", content="jwt token rotation")
        )
        s = castle.catalog.status()
        assert s.total_drawers == 1
        assert "proj" in s.wings

    def test_kg_roundtrip(self, castle):
        castle.graph.kg_add(subject="Kai", predicate="works_on", obj="Orion")
        r = castle.graph.kg_query(entity="Kai")
        assert r.count == 1
        assert r.facts[0]["object"] == "Orion"

    def test_diary_roundtrip(self, castle):
        from swampcastle.models.diary import DiaryWriteCommand
        from swampcastle.services.vault import DiaryReadQuery

        castle.vault.diary_write(
            DiaryWriteCommand(
                agent_name="reviewer",
                entry="found auth bypass",
            )
        )
        resp = castle.vault.diary_read(DiaryReadQuery(agent_name="reviewer"))
        assert len(resp.entries) == 1

    def test_graph_traversal(self, castle):
        for wing, room in [("proj", "auth"), ("proj", "billing"), ("personal", "auth")]:
            castle.vault.add_drawer(
                AddDrawerCommand(wing=wing, room=room, content=f"{wing}/{room} content")
            )
        tunnels = castle.graph.find_tunnels()
        assert any(t["room"] == "auth" for t in tunnels)
