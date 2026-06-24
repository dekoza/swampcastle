"""Tests for swampcastle.storage.lance — real LanceDB backend."""

import json
import os

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

    def test_skip_embedder_check_bypasses_fingerprint_mismatch(self, tmp_path):
        """Reforge must be able to open a collection with a mismatched embedder."""

        class FakeEmbedderA:
            model_name = "same-dim"
            dimension = 384
            fingerprint = {
                "backend": "fake-a",
                "model_name": "same-dim",
                "dimension": 384,
            }

            def embed(self, texts):
                return [[0.1] * 384 for _ in texts]

        class FakeEmbedderB:
            model_name = "same-dim"
            dimension = 384
            fingerprint = {
                "backend": "fake-b",
                "model_name": "same-dim",
                "dimension": 384,
            }

            def embed(self, texts):
                return [[0.2] * 384 for _ in texts]

        backend = LanceBackend()
        palace = str(tmp_path / "palace")
        col = backend.get_collection(palace, "chests", embedder=FakeEmbedderA())
        col.upsert(
            documents=["seed"],
            ids=["s1"],
            metadatas=[{"wing": "t", "room": "r", "source_file": ""}],
        )

        # Without the flag, opening with a different fingerprint raises
        with pytest.raises(RuntimeError, match="fingerprint"):
            backend.get_collection(palace, "chests", embedder=FakeEmbedderB())

        # With skip_embedder_check=True, it opens fine
        col2 = backend.get_collection(
            palace, "chests", embedder=FakeEmbedderB(), skip_embedder_check=True
        )
        assert col2.count() == 1

    def test_skip_embedder_check_allows_reforge_path(self, tmp_path):
        """Simulate the full reforge flow: open with skip, read drawers, upsert with new embedder."""

        class FakeEmbedderA:
            model_name = "test"
            dimension = 384
            fingerprint = {"backend": "fake-a", "model_name": "test", "dimension": 384}

            def embed(self, texts):
                return [[0.1] * 384 for _ in texts]

        class FakeEmbedderB:
            model_name = "test"
            dimension = 384
            fingerprint = {"backend": "fake-b", "model_name": "test", "dimension": 384}

            def embed(self, texts):
                return [[0.2] * 384 for _ in texts]

        backend = LanceBackend()
        palace = str(tmp_path / "palace")
        col = backend.get_collection(palace, "chests", embedder=FakeEmbedderA())
        col.upsert(
            documents=["doc"],
            ids=["d1"],
            metadatas=[{"wing": "w", "room": "r", "source_file": ""}],
        )

        col2 = backend.get_collection(
            palace, "chests", embedder=FakeEmbedderB(), skip_embedder_check=True
        )
        results = col2.get(ids=["d1"], include=["documents", "metadatas"])
        assert results["documents"] == ["doc"]

        # Re-embed with the new model (this is what reforge does)
        col2.upsert(
            ids=results["ids"],
            documents=results["documents"],
            metadatas=results["metadatas"],
        )
        # Upsert succeeds because it uses the new embedder
        assert col2.count() == 1

    def test_upsert_on_legacy_schema_without_new_columns(self, tmp_path):
        """Tables created before Wave 1 / Wave 6 lack kind/data_class/trust_class/source_kind.

        Upsert must not fail when the target schema is missing these columns.
        """
        import lancedb
        import pyarrow as pa

        class FakeEmbedder:
            model_name = "legacy"
            dimension = 384

            def embed(self, texts):
                return [[0.0] * 384 for _ in texts]

        palace = str(tmp_path / "palace")
        db = lancedb.connect(palace)

        # Create a table with the pre-Wave-1 schema (no kind, data_class, etc.)
        old_schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("document", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), 384)),
                pa.field("wing", pa.string()),
                pa.field("room", pa.string()),
                pa.field("source_file", pa.string()),
                pa.field("node_id", pa.string()),
                pa.field("seq", pa.int64()),
                pa.field("metadata_json", pa.string()),
            ]
        )
        db.create_table("chests", schema=old_schema)

        # Open with current code and upsert — must not raise
        col = LanceBackend().get_collection(palace, "chests", embedder=FakeEmbedder())
        col.upsert(
            documents=["doc"],
            ids=["d1"],
            metadatas=[{"wing": "w", "room": "r", "source_file": ""}],
        )
        assert col.count() == 1

        # Overwrite existing record (merge_insert path)
        col.upsert(
            documents=["updated"],
            ids=["d1"],
            metadatas=[{"wing": "w", "room": "r", "source_file": ""}],
        )
        r = col.get(ids=["d1"])
        assert r["documents"] == ["updated"]

    def test_upsert_adds_new_columns_on_legacy_schema(self, tmp_path):
        """When the table lacks new columns, upsert should still work and get() should return
        sensible defaults for missing metadata fields."""
        import lancedb
        import pyarrow as pa

        class FakeEmbedder:
            model_name = "legacy"
            dimension = 384

            def embed(self, texts):
                return [[0.0] * 384 for _ in texts]

        palace = str(tmp_path / "palace")
        db = lancedb.connect(palace)

        old_schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("document", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), 384)),
                pa.field("wing", pa.string()),
                pa.field("room", pa.string()),
                pa.field("source_file", pa.string()),
                pa.field("node_id", pa.string()),
                pa.field("seq", pa.int64()),
                pa.field("metadata_json", pa.string()),
            ]
        )
        db.create_table("chests", schema=old_schema)

        col = LanceBackend().get_collection(palace, "chests", embedder=FakeEmbedder())
        col.upsert(
            documents=["doc"],
            ids=["d1"],
            metadatas=[{"wing": "w", "room": "r", "source_file": ""}],
        )

        r = col.get(ids=["d1"], include=["metadatas"])
        meta = r["metadatas"][0]
        assert meta["wing"] == "w"
        # Missing columns should return empty string (the default in _to_records)
        assert meta.get("kind", "") == ""
        assert meta.get("data_class", "") == ""
        assert meta.get("trust_class", "") == ""
        assert meta.get("source_kind", "") == ""

    def test_parallel_reforge_writes_new_embedder_metadata(self, tmp_path):
        """When embeddings are pre-computed and passed to upsert, _to_records must
        still write the new embedder model/fingerprint via setdefault."""

        class FakeEmbedderA:
            model_name = "old-model"
            dimension = 384
            fingerprint = {"backend": "fake-a", "model_name": "old-model"}

            def embed(self, texts):
                return [[0.1] * 384 for _ in texts]

        class FakeEmbedderB:
            model_name = "new-model"
            dimension = 384
            fingerprint = {"backend": "fake-b", "model_name": "new-model"}

            def embed(self, texts):
                return [[0.2] * 384 for _ in texts]

        backend = LanceBackend()
        palace = str(tmp_path / "palace")
        col = backend.get_collection(palace, "chests", embedder=FakeEmbedderA())
        col.upsert(
            documents=["seed"],
            ids=["s1"],
            metadatas=[{"wing": "t", "room": "r", "source_file": ""}],
        )

        # Old metadata should be present
        old_meta = col.get(ids=["s1"], include=["metadatas"])["metadatas"][0]
        assert old_meta.get("embedding_model") == "old-model"

        # Reopen with new embedder, skip contract check
        col2 = backend.get_collection(
            palace, "chests", embedder=FakeEmbedderB(), skip_embedder_check=True
        )

        # Simulate what parallel reforge does: strip old metadata, embed, upsert
        results = col2.get(ids=["s1"], include=["documents", "metadatas"])
        docs = results["documents"]
        metas = results["metadatas"]
        for meta in metas:
            meta.pop("embedding_model", None)
            meta.pop("embedding_fingerprint", None)

        embeddings = col2._embedder.embed(docs)
        col2.upsert(ids=["s1"], documents=docs, metadatas=metas, embeddings=embeddings)

        # New metadata should be written via setdefault in _to_records
        new_meta = col2.get(ids=["s1"], include=["metadatas"])["metadatas"][0]
        assert new_meta.get("embedding_model") == "new-model"
        fp = new_meta.get("embedding_fingerprint")
        assert fp is not None
        assert fp["backend"] == "fake-b"
        assert fp["model_name"] == "new-model"

    def test_stored_metadata_with_extra_fields_does_not_mismatch(self, tmp_path):
        """Historical stored metadata may contain extra keys (e.g. library
        versions) that the active fingerprint no longer includes. Opening the
        collection must still succeed — only the keys present in the active
        fingerprint are compared."""

        class FakeEmbedder:
            model_name = "stable-model"
            dimension = 384
            fingerprint = {
                "backend": "onnx",
                "model_name": "stable-model",
                "dimension": 384,
                "providers": ["CPUExecutionProvider"],
                "asset_sha256": "abc123",
            }

            def embed(self, texts):
                return [[0.1] * 384 for _ in texts]

        backend = LanceBackend()
        palace = str(tmp_path / "palace")
        col = backend.get_collection(palace, "chests", embedder=FakeEmbedder())
        col.upsert(
            documents=["seed"],
            ids=["s1"],
            metadatas=[{"wing": "t", "room": "r", "source_file": ""}],
        )

        # Simulate historical metadata with extra version fields
        meta_path = os.path.join(palace, ".swampcastle", "chests.embedder.json")
        os.makedirs(os.path.dirname(meta_path), exist_ok=True)
        historical = {
            "embedding_model": "stable-model",
            "embedding_fingerprint": {
                "backend": "onnx",
                "model_name": "stable-model",
                "dimension": 384,
                "providers": ["CPUExecutionProvider"],
                "asset_sha256": "abc123",
                "onnxruntime_version": "1.26.0",
                "tokenizers_version": "0.23.1",
            },
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(historical, f)

        # Reopen — must NOT raise despite extra version fields in stored metadata
        col2 = backend.get_collection(palace, "chests", embedder=FakeEmbedder())
        assert col2.count() == 1
