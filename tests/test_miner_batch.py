import os
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
        # return deterministic vectors
        return [[float(len(t) % 10) for _ in range(self._dim)] for t in texts]


class FakeCollection:
    def __init__(self):
        self.upserts = []

    def upsert(self, *, documents, ids, metadatas=None, embeddings=None):
        self.upserts.append({
            "documents": documents,
            "ids": ids,
            "metadatas": metadatas,
            "embeddings": embeddings,
        })


class FakeFactory:
    def __init__(self, collection, embedder=None):
        self._collection = collection
        self._embedder = embedder

    def open_collection(self, name):
        return self._collection


def make_project(tmp_path: Path):
    cfg = {"wing": "test", "rooms": [{"name": "general", "description": "All files"}]}
    import yaml

    (tmp_path / '.swampcastle.yaml').write_text(yaml.dump(cfg))


def test_batch_embedding_single_flush(tmp_path):
    project = tmp_path
    make_project(project)

    # create files producing several chunks
    f1 = project / 'a.txt'
    f1.write_text('\n'.join(['line'] * 200))
    f2 = project / 'b.txt'
    f2.write_text('\n'.join(['line'] * 200))

    fake_coll = FakeCollection()
    fake_embed = FakeEmbedder(dim=4)
    factory = FakeFactory(fake_coll, embedder=fake_embed)

    # set env to small batch size so buffer will flush once
    os.environ['SWAMPCASTLE_EMBED_BATCH_SIZE'] = '64'

    mine(str(project), str(project / 'palace'), dry_run=False, storage_factory=factory)

    # ensure at least one upsert happened and embeddings provided
    assert len(fake_coll.upserts) >= 1
    for up in fake_coll.upserts:
        assert up['embeddings'] is not None
        assert len(up['embeddings']) == len(up['documents'])
