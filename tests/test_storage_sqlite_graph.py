"""Tests for swampcastle.storage.sqlite_graph — real SQLite KG backend."""

import pytest

from swampcastle.storage.sqlite_graph import SQLiteGraph


class TestSQLiteGraph:
    @pytest.fixture
    def graph(self, tmp_path):
        graph = SQLiteGraph(str(tmp_path / "kg.sqlite3"))
        yield graph
        graph.close()

    def test_add_entity(self, graph):
        eid = graph.add_entity(name="Kai", entity_type="person")
        assert eid == "kai"

    def test_add_triple(self, graph):
        tid = graph.add_triple(subject="Kai", predicate="works_on", obj="Orion")
        assert tid

    def test_query_entity(self, graph):
        graph.add_triple(subject="Kai", predicate="works_on", obj="Orion",
                         valid_from="2025-06-01")
        r = graph.query_entity(name="Kai")
        assert len(r) == 1
        assert r[0]["predicate"] == "works_on"

    def test_invalidate(self, graph):
        graph.add_triple(subject="Kai", predicate="works_on", obj="Orion")
        graph.invalidate(subject="Kai", predicate="works_on", obj="Orion",
                         ended="2026-03-01")
        r = graph.query_entity(name="Kai")
        assert r[0]["valid_to"] == "2026-03-01"

    def test_temporal_as_of(self, graph):
        graph.add_triple(subject="Kai", predicate="works_on", obj="Orion",
                         valid_from="2025-01-01", valid_to="2025-12-31")
        graph.add_triple(subject="Kai", predicate="works_on", obj="Nova",
                         valid_from="2026-01-01")
        mid_2025 = graph.query_entity(name="Kai", as_of="2025-06-15")
        assert len(mid_2025) == 1
        assert mid_2025[0]["object"] == "Orion"

    def test_timeline(self, graph):
        graph.add_triple(subject="A", predicate="r", obj="B", valid_from="2025-01-01")
        graph.add_triple(subject="A", predicate="r", obj="C", valid_from="2026-01-01")
        tl = graph.timeline(entity_name="A")
        assert len(tl) == 2

    def test_stats(self, graph):
        graph.add_triple(subject="X", predicate="likes", obj="Y")
        s = graph.stats()
        assert s["entities"] >= 2
        assert s["triples"] == 1
        assert "likes" in s["relationship_types"]

    def test_query_relationship(self, graph):
        graph.add_triple(subject="A", predicate="likes", obj="B")
        graph.add_triple(subject="C", predicate="likes", obj="D")
        r = graph.query_relationship(predicate="likes")
        assert len(r) == 2

    def test_close(self, graph):
        graph.close()

    def test_direction_incoming(self, graph):
        graph.add_triple(subject="A", predicate="likes", obj="B")
        r = graph.query_entity(name="B", direction="incoming")
        assert len(r) == 1
        assert r[0]["subject"] == "A"

    def test_direction_both(self, graph):
        graph.add_triple(subject="A", predicate="likes", obj="B")
        graph.add_triple(subject="B", predicate="knows", obj="C")
        r = graph.query_entity(name="B", direction="both")
        assert len(r) == 2
