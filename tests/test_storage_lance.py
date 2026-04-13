"""Tests for swampcastle.storage.lance — real LanceDB backend."""

import pytest

from swampcastle.storage.lance import LanceBackend


class TestLanceBackend:
    def test_creates_dir(self, tmp_path):
        palace = str(tmp_path / "new_palace")
        backend = LanceBackend()
        col = backend.get_collection(palace, "test", create=True)
        assert col.count() == 0

    def test_create_false_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            LanceBackend().get_collection(str(tmp_path / "nope"), "t", create=False)


class TestLanceCollection:
    @pytest.fixture
    def col(self, tmp_path):
        return LanceBackend().get_collection(str(tmp_path / "p"), "test", create=True)

    def test_upsert_and_count(self, col):
        col.upsert(documents=["hello"], ids=["1"], metadatas=[{"wing": "w"}])
        assert col.count() == 1

    def test_get_by_id(self, col):
        col.upsert(documents=["doc1"], ids=["a"], metadatas=[{"wing": "w"}])
        r = col.get(ids=["a"])
        assert r["ids"] == ["a"]
        assert r["documents"] == ["doc1"]

    def test_get_by_where(self, col):
        col.upsert(
            documents=["alpha", "beta"],
            ids=["1", "2"],
            metadatas=[{"wing": "a"}, {"wing": "b"}],
        )
        r = col.get(where={"wing": "b"})
        assert r["ids"] == ["2"]

    def test_delete(self, col):
        col.upsert(documents=["x"], ids=["1"], metadatas=[{"wing": "w"}])
        col.delete(ids=["1"])
        assert col.count() == 0

    def test_upsert_overwrites(self, col):
        col.upsert(documents=["v1"], ids=["1"], metadatas=[{"wing": "w"}])
        col.upsert(documents=["v2"], ids=["1"], metadatas=[{"wing": "w"}])
        assert col.count() == 1
        r = col.get(ids=["1"])
        assert r["documents"] == ["v2"]

    def test_query_returns_nested(self, col):
        col.upsert(documents=["machine learning"], ids=["1"], metadatas=[{"wing": "w"}])
        r = col.query(query_texts=["machine learning"], n_results=5)
        assert isinstance(r["ids"][0], list)
        assert len(r["ids"][0]) >= 1

    def test_update_metadata(self, col):
        col.upsert(documents=["doc"], ids=["1"], metadatas=[{"wing": "old"}])
        col.update(ids=["1"], metadatas=[{"wing": "new"}])
        r = col.get(ids=["1"])
        assert r["metadatas"][0]["wing"] == "new"

    def test_get_with_limit_offset(self, col):
        for i in range(10):
            col.upsert(documents=[f"d{i}"], ids=[f"{i}"], metadatas=[{"wing": "w"}])
        r = col.get(limit=3)
        assert len(r["ids"]) == 3
        r2 = col.get(limit=3, offset=3)
        assert len(r2["ids"]) == 3
        assert set(r["ids"]) & set(r2["ids"]) == set()
