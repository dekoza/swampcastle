"""Tests for GraphService."""

import pytest

from swampcastle.models.drawer import AddDrawerCommand
from swampcastle.services.graph import GraphService
from swampcastle.services.vault import VaultService
from swampcastle.storage.memory import (
    InMemoryCollectionStore,
    InMemoryGraphStore,
)
from swampcastle.wal import WalWriter


@pytest.fixture
def col():
    return InMemoryCollectionStore()


@pytest.fixture
def graph():
    return InMemoryGraphStore()


@pytest.fixture
def wal(tmp_path):
    return WalWriter(tmp_path / "wal")


@pytest.fixture
def svc(graph, col, wal):
    return GraphService(graph, col, wal)


class TestKGOperations:
    def test_add_and_query(self, svc):
        svc.kg_add(subject="Kai", predicate="works_on", obj="Orion")
        r = svc.kg_query(entity="Kai")
        assert r.count == 1
        assert r.facts[0]["predicate"] == "works_on"

    def test_invalidate(self, svc):
        svc.kg_add(subject="Kai", predicate="works_on", obj="Orion")
        svc.kg_invalidate(
            subject="Kai", predicate="works_on", obj="Orion", ended="2026-03-01",
        )
        r = svc.kg_query(entity="Kai")
        assert r.facts[0]["valid_to"] == "2026-03-01"

    def test_temporal_query(self, svc):
        svc.kg_add(
            subject="Kai", predicate="works_on", obj="Orion",
            valid_from="2025-01-01",
        )
        svc.kg_invalidate(
            subject="Kai", predicate="works_on", obj="Orion", ended="2025-12-31",
        )
        svc.kg_add(
            subject="Kai", predicate="works_on", obj="Nova",
            valid_from="2026-01-01",
        )

        mid_2025 = svc.kg_query(entity="Kai", as_of="2025-06-15")
        assert mid_2025.count == 1
        assert mid_2025.facts[0]["object"] == "Orion"

        mid_2026 = svc.kg_query(entity="Kai", as_of="2026-06-15")
        assert mid_2026.count == 1
        assert mid_2026.facts[0]["object"] == "Nova"

    def test_timeline(self, svc):
        svc.kg_add(subject="A", predicate="r", obj="B", valid_from="2025-01-01")
        svc.kg_add(subject="A", predicate="r", obj="C", valid_from="2026-01-01")
        r = svc.kg_timeline(entity="A")
        assert r.count == 2

    def test_stats(self, svc):
        svc.kg_add(subject="X", predicate="likes", obj="Y")
        r = svc.kg_stats()
        assert r.entities >= 2
        assert r.triples == 1
        assert "likes" in r.relationship_types

    def test_wal_logged(self, svc, wal):
        svc.kg_add(subject="A", predicate="r", obj="B")
        svc.kg_invalidate(subject="A", predicate="r", obj="B")
        ops = [e["operation"] for e in wal.read_entries()]
        assert "kg_add" in ops
        assert "kg_invalidate" in ops


class TestGraphTraversal:
    @pytest.fixture
    def populated(self, col, svc):
        vault = VaultService(col, WalWriter(svc._wal._dir))
        for wing, room in [
            ("proj", "auth"), ("proj", "billing"), ("proj", "deploy"),
            ("personal", "auth"), ("personal", "journal"),
            ("infra", "deploy"), ("infra", "monitoring"),
        ]:
            vault.add_drawer(AddDrawerCommand(
                wing=wing, room=room, content=f"{wing}/{room} content",
            ))
        return svc

    def test_traverse_from_room(self, populated):
        results = populated.traverse("auth")
        assert len(results) > 0
        assert results[0]["room"] == "auth"
        assert results[0]["hop"] == 0

    def test_traverse_finds_connected(self, populated):
        results = populated.traverse("auth", max_hops=2)
        rooms = {r["room"] for r in results}
        assert "auth" in rooms
        assert "billing" in rooms or "journal" in rooms

    def test_traverse_nonexistent(self, populated):
        results = populated.traverse("nonexistent")
        assert results == []

    def test_find_tunnels(self, populated):
        tunnels = populated.find_tunnels()
        tunnel_rooms = {t["room"] for t in tunnels}
        assert "auth" in tunnel_rooms
        assert "deploy" in tunnel_rooms

    def test_find_tunnels_filtered(self, populated):
        tunnels = populated.find_tunnels(wing_a="proj", wing_b="personal")
        assert all("proj" in t["wings"] and "personal" in t["wings"] for t in tunnels)

    def test_graph_stats(self, populated):
        s = populated.graph_stats()
        assert s["total_rooms"] > 0
        assert s["tunnel_rooms"] > 0
