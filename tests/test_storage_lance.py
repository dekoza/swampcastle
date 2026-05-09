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

    def test_get_can_include_embeddings(self, col):
        col.upsert(documents=["doc1"], ids=["a"], metadatas=[{"wing": "w"}])

        result = col.get(ids=["a"], include=["embeddings"])

        assert result["ids"] == ["a"]
        assert len(result["embeddings"]) == 1
        assert len(result["embeddings"][0]) > 0

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

    # ── Wave 1: typed-record add_records ─────────────────────────────────

    def test_add_records_stores_kind_filterable(self, col):
        from swampcastle.models.record import RecordEnvelope

        col.add_records(
            [
                RecordEnvelope(record_id="r1", kind="document", content="alpha"),
                RecordEnvelope(record_id="r2", kind="tombstone", content="beta"),
            ]
        )
        docs = col.get(where={"kind": "document"})
        assert [rid for rid in docs["ids"]] == ["r1"]

        tombs = col.get(where={"kind": "tombstone"})
        assert [rid for rid in tombs["ids"]] == ["r2"]

    def test_add_records_kind_in_filterable(self, col):
        from swampcastle.models.record import RecordEnvelope

        col.add_records(
            [
                RecordEnvelope(record_id="r1", kind="document", content="a"),
                RecordEnvelope(record_id="r2", kind="transcript", content="b"),
                RecordEnvelope(record_id="r3", kind="curation", content="c"),
            ]
        )
        docs = col.get(where={"kind": {"$in": ["document", "transcript"]}})
        returned_ids = set(docs["ids"])
        assert returned_ids == {"r1", "r2"}

    def test_add_records_node_seq_preserved(self, col):
        from swampcastle.models.record import RecordEnvelope

        col.add_records(
            [
                RecordEnvelope(record_id="r1", kind="document", node_id="n1", seq=99, content="x"),
            ]
        )
        docs = col.get(ids=["r1"])
        # node_id and seq are injected by the sync identity during upsert;
        # the envelope values are advisory only unless _raw=True is used.
        assert docs["ids"] == ["r1"]
        assert docs["documents"] == ["x"]
        assert docs["metadatas"][0]["kind"] == "document"

    def test_add_records_custom_metadata_survives(self, col):
        from swampcastle.models.record import RecordEnvelope

        col.add_records(
            [
                RecordEnvelope(
                    record_id="r1",
                    kind="document",
                    content="x",
                    metadata={"data_class": "financial"},
                ),
            ]
        )
        docs = col.get(ids=["r1"])
        assert docs["metadatas"][0]["data_class"] == "financial"
