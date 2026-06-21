"""Tests for swampcastle.storage.base — ABC contract enforcement + default implementations."""

from datetime import datetime, timezone

import pytest

from swampcastle.models.record import RecordEnvelope
from swampcastle.storage.base import CollectionStore, GraphStore, _env_meta


class TestCollectionStoreABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            CollectionStore()

    def test_incomplete_subclass_raises(self):
        class Partial(CollectionStore):
            def upsert(self, **kw):
                pass

        with pytest.raises(TypeError):
            Partial()

    def test_complete_subclass_ok(self):
        class Complete(CollectionStore):
            def add(self, *, documents, ids, metadatas=None):
                pass

            def upsert(self, *, documents, ids, metadatas=None):
                pass

            def query(self, *, query_texts, n_results=5, where=None, include=None):
                pass

            def get(self, *, ids=None, where=None, limit=None, offset=None, include=None):
                pass

            def delete(self, *, ids):
                pass

            def update(self, *, ids, documents=None, metadatas=None):
                pass

            def count(self):
                pass

        assert isinstance(Complete(), CollectionStore)


class TestGraphStoreABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            GraphStore()

    def test_incomplete_subclass_raises(self):
        class Partial(GraphStore):
            def add_entity(self, **kw):
                pass

        with pytest.raises(TypeError):
            Partial()

    def test_complete_subclass_ok(self):
        class Complete(GraphStore):
            def add_entity(self, *, name, entity_type="unknown", properties=None):
                pass

            def add_triple(
                self,
                *,
                subject,
                predicate,
                obj,
                valid_from=None,
                valid_to=None,
                confidence=1.0,
                source_closet=None,
                source_file=None,
            ):
                pass

            def query_entity(self, *, name, as_of=None, direction="outgoing"):
                pass

            def query_relationship(self, *, predicate, as_of=None):
                pass

            def invalidate(self, *, subject, predicate, obj, ended=None):
                pass

            def timeline(self, *, entity_name=None):
                pass

            def stats(self):
                pass

            def propose_triple(
                self,
                *,
                subject_text,
                predicate,
                object_text,
                confidence,
                modality,
                polarity,
                evidence_drawer_id,
                evidence_text,
                extractor_version,
                valid_from=None,
                valid_to=None,
                source_file=None,
                wing=None,
                room=None,
            ):
                pass

            def get_candidate_triple(self, *, candidate_id):
                pass

            def list_candidate_triples(
                self,
                *,
                status=None,
                predicate=None,
                min_confidence=None,
                wing=None,
                room=None,
                limit=50,
                offset=0,
            ):
                pass

            def set_candidate_status(self, *, candidate_id, status, reviewed_at=None):
                pass

            def close(self):
                pass

        assert isinstance(Complete(), GraphStore)


# ── CollectionStore.add_records default implementation ──────────────────


class TestAddRecordsDefault:
    """Test the default add_records() implementation on a concrete store."""

    def _make_store(self):
        class ConcreteStore(CollectionStore):
            def __init__(self):
                self.upsert_calls = []

            def add(self, *, documents, ids, metadatas=None):
                self.upsert(documents=documents, ids=ids, metadatas=metadatas)

            def upsert(self, *, documents, ids, metadatas=None):
                self.upsert_calls.append(
                    {"documents": documents, "ids": ids, "metadatas": metadatas}
                )

            def query(self, *, query_texts, n_results=5, where=None, include=None):
                return {"ids": [], "documents": [], "metadatas": [], "distances": []}

            def get(self, *, ids=None, where=None, limit=None, offset=None, include=None):
                return {"ids": [], "documents": [], "metadatas": []}

            def delete(self, *, ids):
                pass

            def update(self, *, ids, documents=None, metadatas=None):
                pass

            def count(self):
                return 0

        return ConcreteStore()

    def test_delegates_to_upsert(self):
        store = self._make_store()
        env = RecordEnvelope(record_id="r1", kind="document", content="hello")
        store.add_records([env])

        assert len(store.upsert_calls) == 1
        assert store.upsert_calls[0]["ids"] == ["r1"]
        assert store.upsert_calls[0]["documents"] == ["hello"]

    def test_multiple_envelopes(self):
        store = self._make_store()
        envs = [
            RecordEnvelope(record_id="r1", kind="document", content="a"),
            RecordEnvelope(record_id="r2", kind="transcript", content="b"),
        ]
        store.add_records(envs)

        assert len(store.upsert_calls) == 1
        assert store.upsert_calls[0]["ids"] == ["r1", "r2"]
        assert store.upsert_calls[0]["documents"] == ["a", "b"]


# ── _env_meta helper ────────────────────────────────────────────────────


class TestEnvMeta:
    def test_flattens_envelope_fields(self):
        env = RecordEnvelope(
            record_id="r1",
            kind="document",
            node_id="node-1",
            seq=42,
            content="test",
        )
        meta = _env_meta(env)

        assert meta["kind"] == "document"
        assert meta["node_id"] == "node-1"
        assert meta["seq"] == 42
        assert "updated_at" in meta

    def test_preserves_custom_metadata(self):
        env = RecordEnvelope(
            record_id="r1",
            kind="document",
            content="test",
            metadata={"wing": "proj", "room": "auth", "custom_key": "value"},
        )
        meta = _env_meta(env)

        assert meta["wing"] == "proj"
        assert meta["room"] == "auth"
        assert meta["custom_key"] == "value"

    def test_kind_defaults_to_envelope_kind(self):
        env = RecordEnvelope(record_id="r1", kind="tombstone", content="")
        meta = _env_meta(env)

        assert meta["kind"] == "tombstone"

    def test_kind_setdefault_does_not_override_existing(self):
        env = RecordEnvelope(
            record_id="r1",
            kind="document",
            content="test",
            metadata={"kind": "override"},
        )
        meta = _env_meta(env)

        # setdefault should not override an existing key
        assert meta["kind"] == "override"

    def test_does_not_mutate_original_metadata(self):
        original = {"wing": "proj"}
        env = RecordEnvelope(
            record_id="r1",
            kind="document",
            content="test",
            metadata=original,
        )
        meta = _env_meta(env)

        assert "kind" not in original
        assert "node_id" not in original
