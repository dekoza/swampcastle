import os
import shutil
import tempfile

from swampcastle.mining.convo import mine_convos
from swampcastle.storage.lance import LanceBackend
from swampcastle.storage.memory import InMemoryStorageFactory


def _get_test_collection(path, name="swampcastle_chests"):
    return LanceBackend().get_collection(path, name, create=True)


def test_convo_mining():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
        f.write(
            "> What is memory?\nMemory is persistence.\n\n> Why does it matter?\nIt enables continuity.\n\n> How do we build it?\nWith structured storage.\n"
        )

    palace_path = os.path.join(tmpdir, "palace")
    mine_convos(tmpdir, palace_path, wing="test_convos")

    col = _get_test_collection(palace_path)
    assert col.count() >= 2

    # Verify search works
    results = col.query(query_texts=["memory persistence"], n_results=1)
    assert len(results["documents"][0]) > 0

    shutil.rmtree(tmpdir, ignore_errors=True)


def test_convo_mining_accepts_storage_factory():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
        f.write(
            "> What is memory?\nMemory is persistence.\n\n> Why does it matter?\nIt enables continuity.\n\n> How do we build it?\nWith structured storage.\n"
        )

    factory = InMemoryStorageFactory()
    mine_convos(tmpdir, os.path.join(tmpdir, "palace"), wing="test_convos", storage_factory=factory)

    col = factory.open_collection("swampcastle_chests")
    assert col.count() >= 2

    shutil.rmtree(tmpdir, ignore_errors=True)


def test_convo_mining_tags_contributor_metadata():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
        f.write(
            "> What is memory?\nMemory is persistence.\n\n> Why does it matter?\nIt enables continuity.\n\n> How do we build it?\nWith structured storage.\n"
        )

    with open(os.path.join(tmpdir, ".swampcastle.yaml"), "w") as f:
        import yaml

        yaml.dump({"wing": "test_convos", "team": ["dekoza", "sarah"]}, f)

    factory = InMemoryStorageFactory()
    from unittest.mock import patch

    with patch(
        "swampcastle.mining.contributor._git_last_author",
        return_value="dekoza",
    ):
        mine_convos(
            tmpdir, os.path.join(tmpdir, "palace"), wing="test_convos", storage_factory=factory
        )

    col = factory.open_collection("swampcastle_chests")
    rows = col.get(include=["metadatas"])
    assert rows["metadatas"]
    assert all(meta.get("contributor") == "dekoza" for meta in rows["metadatas"])

    shutil.rmtree(tmpdir, ignore_errors=True)
