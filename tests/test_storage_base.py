"""Tests for swampcastle.storage.base — ABC contract enforcement."""

import pytest

from swampcastle.storage.base import CollectionStore, GraphStore


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

            def close(self):
                pass

        assert isinstance(Complete(), GraphStore)
