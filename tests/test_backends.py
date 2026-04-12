"""Tests for swampcastle.backends — ABC contract, detection, LanceBackend."""

import os

import pytest

from swampcastle.backends.base import BaseCollection
from swampcastle.backends import detect_backend


class TestBaseCollectionContract:
    """BaseCollection ABC enforces method signatures."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseCollection()

    def test_subclass_missing_method_raises(self):
        class Incomplete(BaseCollection):
            def add(self, *, documents, ids, metadatas=None):
                pass

        with pytest.raises(TypeError):
            Incomplete()

    def test_complete_subclass_instantiates(self):
        class Complete(BaseCollection):
            def add(self, *, documents, ids, metadatas=None): pass
            def upsert(self, *, documents, ids, metadatas=None): pass
            def query(self, *, query_texts, n_results=5, where=None, include=None): pass
            def get(self, *, ids=None, where=None, limit=None, offset=None, include=None): pass
            def delete(self, *, ids): pass
            def update(self, *, ids, documents=None, metadatas=None): pass
            def count(self): pass

        obj = Complete()
        assert isinstance(obj, BaseCollection)


class TestDetectBackend:
    def test_missing_dir_returns_lance(self, tmp_path):
        assert detect_backend(str(tmp_path / "nope")) == "lance"

    def test_empty_dir_returns_lance(self, tmp_path):
        assert detect_backend(str(tmp_path)) == "lance"

    def test_lance_dir_detected(self, tmp_path):
        (tmp_path / "my_table.lance").mkdir()
        assert detect_backend(str(tmp_path)) == "lance"

    def test_chroma_sqlite_detected(self, tmp_path):
        (tmp_path / "chroma.sqlite3").touch()
        assert detect_backend(str(tmp_path)) == "chroma"

    def test_lance_takes_precedence_over_chroma(self, tmp_path):
        (tmp_path / "table.lance").mkdir()
        (tmp_path / "chroma.sqlite3").touch()
        assert detect_backend(str(tmp_path)) == "lance"


class TestLanceBackend:
    def test_get_collection_creates_dir(self, tmp_path):
        from swampcastle.backends.lance import LanceBackend

        palace = str(tmp_path / "new_palace")
        backend = LanceBackend()
        col = backend.get_collection(palace, "test_col", create=True)
        assert os.path.isdir(palace)
        assert col.count() == 0

    def test_get_collection_create_false_missing_raises(self, tmp_path):
        from swampcastle.backends.lance import LanceBackend

        with pytest.raises(FileNotFoundError):
            LanceBackend().get_collection(
                str(tmp_path / "nope"), "test_col", create=False,
            )

    def test_roundtrip_upsert_get(self, tmp_path):
        from swampcastle.backends.lance import LanceBackend

        palace = str(tmp_path / "palace")
        col = LanceBackend().get_collection(palace, "test_col", create=True)

        col.upsert(
            documents=["hello world"],
            ids=["id1"],
            metadatas=[{"wing": "test", "room": "r1"}],
        )
        assert col.count() == 1

        result = col.get(ids=["id1"])
        assert result["ids"] == ["id1"]
        assert result["documents"] == ["hello world"]

    def test_delete_removes_record(self, tmp_path):
        from swampcastle.backends.lance import LanceBackend

        palace = str(tmp_path / "palace")
        col = LanceBackend().get_collection(palace, "test_col", create=True)
        col.upsert(
            documents=["to delete"],
            ids=["del1"],
            metadatas=[{"wing": "w"}],
        )
        assert col.count() == 1
        col.delete(ids=["del1"])
        assert col.count() == 0

    def test_update_changes_metadata(self, tmp_path):
        from swampcastle.backends.lance import LanceBackend

        palace = str(tmp_path / "palace")
        col = LanceBackend().get_collection(palace, "test_col", create=True)
        col.upsert(
            documents=["original"],
            ids=["u1"],
            metadatas=[{"wing": "w", "room": "r1"}],
        )

        col.update(ids=["u1"], metadatas=[{"wing": "w", "room": "r2"}])
        result = col.get(ids=["u1"])
        meta = result["metadatas"][0]
        assert meta["room"] == "r2"
