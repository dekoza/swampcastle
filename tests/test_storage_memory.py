"""Tests for swampcastle.storage.memory — InMemory backends."""

import pytest

from swampcastle.storage.memory import (
    InMemoryCollectionStore,
    InMemoryGraphStore,
    InMemoryStorageFactory,
)


class TestInMemoryCollection:
    @pytest.fixture
    def col(self):
        return InMemoryCollectionStore()

    def test_empty_count(self, col):
        assert col.count() == 0

    def test_upsert_and_count(self, col):
        col.upsert(documents=["hello"], ids=["1"], metadatas=[{"wing": "w"}])
        assert col.count() == 1

    def test_upsert_overwrites(self, col):
        col.upsert(documents=["v1"], ids=["1"], metadatas=[{"wing": "w"}])
        col.upsert(documents=["v2"], ids=["1"], metadatas=[{"wing": "w"}])
        assert col.count() == 1
        result = col.get(ids=["1"])
        assert result["documents"] == ["v2"]

    def test_add_delegates_to_upsert(self, col):
        col.add(documents=["doc"], ids=["1"], metadatas=[{"wing": "w"}])
        assert col.count() == 1

    def test_get_by_ids(self, col):
        col.upsert(documents=["a", "b"], ids=["1", "2"],
                    metadatas=[{"wing": "w1"}, {"wing": "w2"}])
        result = col.get(ids=["2"])
        assert result["ids"] == ["2"]
        assert result["documents"] == ["b"]
        assert result["metadatas"] == [{"wing": "w2"}]

    def test_get_by_where(self, col):
        col.upsert(documents=["a", "b"], ids=["1", "2"],
                    metadatas=[{"wing": "alpha"}, {"wing": "beta"}])
        result = col.get(where={"wing": "beta"})
        assert result["ids"] == ["2"]

    def test_get_with_limit(self, col):
        for i in range(10):
            col.upsert(documents=[f"d{i}"], ids=[f"{i}"],
                       metadatas=[{"wing": "w"}])
        result = col.get(limit=3)
        assert len(result["ids"]) == 3

    def test_get_with_offset(self, col):
        for i in range(5):
            col.upsert(documents=[f"d{i}"], ids=[f"{i}"],
                       metadatas=[{"wing": "w"}])
        all_ids = col.get()["ids"]
        offset_ids = col.get(offset=2)["ids"]
        assert offset_ids == all_ids[2:]

    def test_get_empty(self, col):
        result = col.get(ids=["nonexistent"])
        assert result == {"ids": [], "documents": [], "metadatas": []}

    def test_delete(self, col):
        col.upsert(documents=["a"], ids=["1"], metadatas=[{"wing": "w"}])
        col.delete(ids=["1"])
        assert col.count() == 0

    def test_delete_nonexistent_ok(self, col):
        col.delete(ids=["nope"])

    def test_update_metadata(self, col):
        col.upsert(documents=["doc"], ids=["1"], metadatas=[{"wing": "old"}])
        col.update(ids=["1"], metadatas=[{"wing": "new"}])
        result = col.get(ids=["1"])
        assert result["metadatas"][0]["wing"] == "new"

    def test_update_document(self, col):
        col.upsert(documents=["v1"], ids=["1"], metadatas=[{"wing": "w"}])
        col.update(ids=["1"], documents=["v2"])
        result = col.get(ids=["1"])
        assert result["documents"] == ["v2"]

    def test_query_returns_nested_format(self, col):
        col.upsert(documents=["machine learning is cool"], ids=["1"],
                    metadatas=[{"wing": "tech"}])
        result = col.query(query_texts=["machine learning"], n_results=5)
        assert "ids" in result
        assert isinstance(result["ids"], list)
        assert isinstance(result["ids"][0], list)

    def test_query_with_where_filter(self, col):
        col.upsert(documents=["alpha doc", "beta doc"], ids=["1", "2"],
                    metadatas=[{"wing": "a"}, {"wing": "b"}])
        result = col.query(query_texts=["doc"], n_results=5, where={"wing": "b"})
        assert all(id_ == "2" for id_ in result["ids"][0])

    def test_get_where_and(self, col):
        col.upsert(
            documents=["d1", "d2", "d3"],
            ids=["1", "2", "3"],
            metadatas=[
                {"wing": "a", "room": "r1"},
                {"wing": "a", "room": "r2"},
                {"wing": "b", "room": "r1"},
            ],
        )
        result = col.get(where={"$and": [{"wing": "a"}, {"room": "r1"}]})
        assert result["ids"] == ["1"]


class TestInMemoryGraph:
    @pytest.fixture
    def graph(self):
        return InMemoryGraphStore()

    def test_add_entity(self, graph):
        eid = graph.add_entity(name="Kai", entity_type="person")
        assert eid == "kai"

    def test_add_triple(self, graph):
        tid = graph.add_triple(subject="Kai", predicate="works_on", obj="Orion")
        assert tid

    def test_query_entity(self, graph):
        graph.add_triple(subject="Kai", predicate="works_on", obj="Orion",
                         valid_from="2025-06-01")
        results = graph.query_entity(name="Kai")
        assert len(results) == 1
        assert results[0]["predicate"] == "works_on"
        assert results[0]["object"] == "Orion"

    def test_invalidate(self, graph):
        graph.add_triple(subject="Kai", predicate="works_on", obj="Orion")
        graph.invalidate(subject="Kai", predicate="works_on", obj="Orion",
                         ended="2026-03-01")
        results = graph.query_entity(name="Kai")
        assert results[0]["valid_to"] == "2026-03-01"

    def test_temporal_filter(self, graph):
        graph.add_triple(subject="Kai", predicate="works_on", obj="Orion",
                         valid_from="2025-01-01", valid_to="2025-12-31")
        graph.add_triple(subject="Kai", predicate="works_on", obj="Nova",
                         valid_from="2026-01-01")

        mid_2025 = graph.query_entity(name="Kai", as_of="2025-06-15")
        assert len(mid_2025) == 1
        assert mid_2025[0]["object"] == "Orion"

        mid_2026 = graph.query_entity(name="Kai", as_of="2026-06-15")
        assert len(mid_2026) == 1
        assert mid_2026[0]["object"] == "Nova"

    def test_timeline(self, graph):
        graph.add_triple(subject="Kai", predicate="works_on", obj="A",
                         valid_from="2025-01-01")
        graph.add_triple(subject="Kai", predicate="works_on", obj="B",
                         valid_from="2026-01-01")
        tl = graph.timeline(entity_name="Kai")
        assert len(tl) == 2
        assert tl[0]["valid_from"] <= tl[1]["valid_from"]

    def test_stats(self, graph):
        graph.add_triple(subject="A", predicate="rel", obj="B")
        s = graph.stats()
        assert s["entities"] >= 2
        assert s["triples"] == 1

    def test_close(self, graph):
        graph.close()

    def test_query_relationship(self, graph):
        graph.add_triple(subject="A", predicate="likes", obj="B")
        graph.add_triple(subject="C", predicate="likes", obj="D")
        results = graph.query_relationship(predicate="likes")
        assert len(results) == 2


class TestInMemoryFactory:
    def test_creates_collection_and_graph(self):
        factory = InMemoryStorageFactory()
        col = factory.open_collection("test")
        graph = factory.open_graph()
        assert col.count() == 0
        assert graph.stats()["triples"] == 0

    def test_same_collection_name_same_instance(self):
        factory = InMemoryStorageFactory()
        a = factory.open_collection("x")
        b = factory.open_collection("x")
        a.upsert(documents=["doc"], ids=["1"], metadatas=[{}])
        assert b.count() == 1
