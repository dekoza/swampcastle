import pytest
import yaml
from pathlib import Path

from swampcastle.mining.miner import mine


class FakeEmbedder:
    def __init__(self, dim=3):
        self._dim = dim
        self.model_name = "fake"

    @property
    def dimension(self):
        return self._dim

    def embed(self, texts):
        return [[float(len(t) % 10) for _ in range(self._dim)] for t in texts]


class FakeCollection:
    def __init__(self):
        self.upserts = []
        self.fail_on_next_upsert = False

    def upsert(self, *, documents, ids, metadatas=None, embeddings=None):
        if self.fail_on_next_upsert:
            self.fail_on_next_upsert = False
            raise RuntimeError("simulated storage failure")
        self.upserts.append(
            {
                "documents": documents,
                "ids": ids,
                "metadatas": metadatas,
                "embeddings": embeddings,
            }
        )

    def get(self, *, ids=None, where=None, limit=None, offset=None, include=None):
        return {"ids": [], "documents": [], "metadatas": []}

    def delete(self, *, ids=None, where=None):
        pass


class FakeFactory:
    def __init__(self, collection, embedder=None):
        self._collection = collection
        self._embedder = embedder

    def open_collection(self, name):
        return self._collection


def make_project(tmp_path: Path):
    cfg = {"wing": "test", "rooms": [{"name": "general", "description": "All files"}]}
    (tmp_path / ".swampcastle.yaml").write_text(yaml.dump(cfg))


def test_batch_embedding_single_flush(tmp_path, monkeypatch):
    make_project(tmp_path)

    (tmp_path / "a.txt").write_text("\n".join(["line"] * 200))
    (tmp_path / "b.txt").write_text("\n".join(["line"] * 200))

    fake_coll = FakeCollection()
    factory = FakeFactory(fake_coll, embedder=FakeEmbedder(dim=4))

    monkeypatch.setenv("SWAMPCASTLE_EMBED_BATCH_SIZE", "64")

    mine(str(tmp_path), str(tmp_path / "palace"), dry_run=False, storage_factory=factory)

    assert len(fake_coll.upserts) >= 1
    for up in fake_coll.upserts:
        assert up["embeddings"] is not None
        assert len(up["embeddings"]) == len(up["documents"])


def test_flush_failure_propagates(tmp_path, monkeypatch):
    """A storage error in flush() must propagate; no silent data loss."""
    from swampcastle.mining.miner import EmbeddingBuffer

    fake_coll = FakeCollection()
    fake_coll.fail_on_next_upsert = True
    buf = EmbeddingBuffer(fake_coll, embedder=FakeEmbedder(dim=2), batch_size=100)
    buf.add("hello world", "id_1", {})

    with pytest.raises(RuntimeError, match="simulated storage failure"):
        buf.flush()

    # Buffer must be cleared even after failure to prevent double-flush
    assert buf._docs == []
    assert buf.stored_count == 0


def test_stored_count_accurate(tmp_path, monkeypatch):
    """stored_count reflects actually-stored docs, not just queued ones."""
    from swampcastle.mining.miner import EmbeddingBuffer

    fake_coll = FakeCollection()
    buf = EmbeddingBuffer(fake_coll, embedder=FakeEmbedder(dim=2), batch_size=100)

    buf.add("doc one", "id_1", {})
    buf.add("doc two", "id_2", {})
    assert buf.stored_count == 0  # not yet flushed

    buf.flush()
    assert buf.stored_count == 2

    buf.add("doc three", "id_3", {})
    buf.flush()
    assert buf.stored_count == 3


def test_batch_size_zero_never_autoflushes():
    """batch_size=0 must mean never auto-flush: documents accumulate until explicit flush()."""
    from swampcastle.mining.miner import EmbeddingBuffer

    fake_coll = FakeCollection()
    buf = EmbeddingBuffer(fake_coll, embedder=FakeEmbedder(dim=2), batch_size=0)
    assert buf.batch_size == 0

    # Adding documents must NOT trigger auto-flush
    buf.add("doc one", "id_1", {})
    buf.add("doc two", "id_2", {})
    buf.add("doc three", "id_3", {})
    assert fake_coll.upserts == [], "batch_size=0 must never auto-flush"
    assert buf.stored_count == 0

    # Explicit flush must still work
    buf.flush()
    assert buf.stored_count == 3


def test_embedding_buffer_uses_tuned_default_batch_size(monkeypatch):
    """Without explicit overrides, buffer size should come from tuned defaults."""
    from swampcastle.mining.miner import EmbeddingBuffer

    monkeypatch.delenv("SWAMPCASTLE_EMBED_BATCH_SIZE", raising=False)
    monkeypatch.setattr(
        "swampcastle.mining.miner.suggest_onnx_tuning",
        lambda: {
            "onnx_intra_op_threads": 4,
            "onnx_inter_op_threads": 1,
            "embed_batch_size": 128,
        },
    )

    fake_coll = FakeCollection()
    buf = EmbeddingBuffer(fake_coll, embedder=FakeEmbedder(dim=2))
    assert buf.batch_size == 128


def test_flush_restores_buffer_on_embedder_failure():
    """Embedder failure must NOT silently discard documents."""
    from swampcastle.mining.miner import EmbeddingBuffer

    class BombEmbedder:
        model_name = "bomb"

        def embed(self, texts):
            raise RuntimeError("embedder exploded")

    fake_coll = FakeCollection()
    buf = EmbeddingBuffer(fake_coll, embedder=BombEmbedder(), batch_size=100)
    buf.add("doc one", "id_1", {"meta": 1})
    buf.add("doc two", "id_2", {"meta": 2})

    with pytest.raises(RuntimeError, match="embedder exploded"):
        buf.flush()

    # Documents must be preserved for retry
    assert len(buf._docs) == 2
    assert buf._ids == ["id_1", "id_2"]
    assert buf.stored_count == 0


def test_force_no_skeleton_does_not_bypass_mtime_check(tmp_path):
    """force_no_skeleton=True must not bypass the already-mined mtime check."""
    from swampcastle.mining.miner import process_file
    import yaml

    project = tmp_path / "proj"
    project.mkdir()
    (project / ".swampcastle.yaml").write_text(
        yaml.dump({"wing": "test", "rooms": [{"name": "general", "description": ""}]})
    )
    src = project / "code.py"
    src.write_text("def f():\n    return 1\n" * 10)  # enough to exceed MIN_CHUNK_SIZE

    class TrackingCollection:
        """Records how many times each source_file was seen."""

        def __init__(self):
            self.upserts = []
            self._stored_meta = None

        def get(self, *, ids=None, where=None, limit=None, offset=None, include=None):
            if self._stored_meta is not None:
                return {"ids": ["d1"], "metadatas": [self._stored_meta]}
            return {"ids": [], "metadatas": []}

        def upsert(self, *, documents, ids, metadatas=None, embeddings=None):
            self.upserts.append(ids)
            import os

            self._stored_meta = {
                "source_file": str(src),
                "source_mtime": os.path.getmtime(str(src)),
            }

        def delete(self, **kwargs):
            pass

    coll = TrackingCollection()
    rooms = [{"name": "general", "description": ""}]

    # First mine: stores the file
    process_file(src, project, coll, "test", rooms, "agent", dry_run=False)
    assert len(coll.upserts) == 1

    # Second mine with force_no_skeleton=True: file unchanged, must be skipped
    process_file(src, project, coll, "test", rooms, "agent", dry_run=False, force_no_skeleton=True)
    assert len(coll.upserts) == 1, "force_no_skeleton=True must not bypass mtime skip"
