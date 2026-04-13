import os
import tempfile
import shutil
from swampcastle.storage.lance import LanceBackend
from swampcastle.storage.memory import InMemoryStorageFactory
_get_test_collection = lambda path, name="swampcastle_chests": LanceBackend().get_collection(path, name, create=True)
from swampcastle.mining.convo import mine_convos


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
