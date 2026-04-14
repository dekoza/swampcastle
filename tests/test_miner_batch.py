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
        self.upserts.append({
            "documents": documents,
            "ids": ids,
            "metadatas": metadatas,
            "embeddings": embeddings,
        })

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
    (tmp_path / '.swampcastle.yaml').write_text(yaml.dump(cfg))


def test_batch_embedding_single_flush(tmp_path, monkeypatch):
    make_project(tmp_path)

    (tmp_path / 'a.txt').write_text('\n'.join(['line'] * 200))
    (tmp_path / 'b.txt').write_text('\n'.join(['line'] * 200))

    fake_coll = FakeCollection()
    factory = FakeFactory(fake_coll, embedder=FakeEmbedder(dim=4))

    monkeypatch.setenv('SWAMPCASTLE_EMBED_BATCH_SIZE', '64')

    mine(str(tmp_path), str(tmp_path / 'palace'), dry_run=False, storage_factory=factory)

    assert len(fake_coll.upserts) >= 1
    for up in fake_coll.upserts:
        assert up['embeddings'] is not None
        assert len(up['embeddings']) == len(up['documents'])


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


def test_batch_size_zero_is_respected(tmp_path):
    """Explicit batch_size=0 must not silently fall back to a larger default."""
    from swampcastle.mining.miner import EmbeddingBuffer

    fake_coll = FakeCollection()
    buf = EmbeddingBuffer(fake_coll, embedder=FakeEmbedder(dim=2), batch_size=0)
    # batch_size=0 means never auto-flush (every add goes past the threshold check)
    # The constructor must store 0, not replace it with a default.
    assert buf.batch_size == 0
