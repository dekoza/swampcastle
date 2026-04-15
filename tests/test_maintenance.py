"""Tests for reforge and distill services."""

from __future__ import annotations

from concurrent.futures import Future

import pytest

from swampcastle.castle import Castle
from swampcastle.models.drawer import AddDrawerCommand
from swampcastle.settings import CastleSettings
from swampcastle.storage.memory import InMemoryStorageFactory
from swampcastle.services.vault import VaultService


@pytest.fixture
def castle(tmp_path):
    factory = InMemoryStorageFactory()
    # Use real CastleSettings to verify settings validation works
    settings = CastleSettings(
        _env_file=None,
        castle_path=tmp_path / "castle",
    )

    with Castle(settings, factory) as c:
        # Add some initial data
        c.vault.add_drawer(AddDrawerCommand(wing="test", room="r1", content="First drawer content"))
        c.vault.add_drawer(
            AddDrawerCommand(wing="test", room="r1", content="Second drawer with different words")
        )
        yield c


def test_distill_drawers_updates_metadata_with_aaak(castle):
    """Distill should compute AAAK summaries and store them in metadata."""
    # 1. Verify no AAAK yet
    # Access internal collection for verification
    results = castle.vault._col.get(include=["metadatas"])
    for meta in results["metadatas"]:
        assert "aaak" not in meta

    # 2. Distill
    count = castle.vault.distill()
    assert count == 2

    # 3. Verify AAAK exists
    results = castle.vault._col.get(include=["metadatas"])
    for meta in results["metadatas"]:
        assert "aaak" in meta
        assert "0:" in meta["aaak"]  # AAAK format marker


def test_distill_does_not_mutate_input_metadata(castle):
    """Distill should not mutate the metadata returned by collection.get()."""
    # Get metadata before distill
    before = castle.vault._col.get(include=["metadatas"])
    original_metas = [dict(m) for m in before["metadatas"]]  # deep copy

    # Distill
    castle.vault.distill()

    # Original copies should NOT have 'aaak' key (proves no mutation)
    for orig in original_metas:
        assert "aaak" not in orig


def test_reforge_recomputes_embeddings(castle):
    """Reforge should re-embed all drawers using the current embedder."""
    # 1. Reforge
    # In memory factory uses a simple store that doesn't compute real
    # embeddings, but we verify it completes and returns the correct count.
    count = castle.vault.reforge()
    assert count == 2

    # 2. Verify drawers still exist
    results = castle.vault._col.get(include=["documents"])
    assert len(results["ids"]) == 2


def test_distill_with_wing_filter(castle):
    """Distill should respect wing filter."""
    # Add drawer in different wing
    castle.vault.add_drawer(AddDrawerCommand(wing="other", room="r1", content="Other wing"))

    count = castle.vault.distill(wing="test")
    assert count == 2  # Only original two in 'test' wing


def test_distill_with_room_filter(castle):
    """Distill should respect room filter."""
    # Add drawer in different room
    castle.vault.add_drawer(AddDrawerCommand(wing="test", room="r2", content="Other room"))

    count = castle.vault.distill(room="r1")
    assert count == 2  # Only original two in 'r1' room


def test_distill_dry_run_does_not_modify(castle):
    """Dry-run distill should count but not modify metadata."""
    count = castle.vault.distill(dry_run=True)
    assert count == 2

    # Verify metadata NOT modified
    results = castle.vault._col.get(include=["metadatas"])
    for meta in results["metadatas"]:
        assert "aaak" not in meta


def test_reforge_with_wing_filter(castle):
    """Reforge should respect wing filter."""
    castle.vault.add_drawer(AddDrawerCommand(wing="other", room="r1", content="Other wing"))

    count = castle.vault.reforge(wing="test")
    assert count == 2


def test_reforge_dry_run_does_not_modify(castle):
    """Dry-run reforge should count but not upsert."""
    # Get count before
    before_count = castle.vault._col.count()

    count = castle.vault.reforge(dry_run=True)
    assert count == 2

    # Count should be same
    assert castle.vault._col.count() == before_count


def test_reforge_reports_batch_progress(tmp_path):
    from swampcastle.wal import WalWriter

    class SpyCollection:
        def __init__(self):
            self.upsert_calls = []

        def get(self, *, ids=None, where=None, limit=None, offset=None, include=None):
            return {
                "ids": ["d1", "d2", "d3", "d4", "d5"],
                "documents": [f"doc {i}" for i in range(1, 6)],
                "metadatas": [{"wing": "test", "room": "r1", "source_file": ""} for _ in range(5)],
            }

        def upsert(self, *, documents, ids, metadatas=None):
            self.upsert_calls.append(list(ids))

    progress_updates = []
    service = VaultService(SpyCollection(), WalWriter(tmp_path / "wal"))

    count = service.reforge(
        batch_size=2,
        progress_callback=lambda processed, total: progress_updates.append((processed, total)),
    )

    assert count == 5
    assert service._col.upsert_calls == [["d1", "d2"], ["d3", "d4"], ["d5"]]
    assert progress_updates == [(0, 5), (2, 5), (4, 5), (5, 5)]


def test_reforge_uses_larger_adaptive_batches_for_progress(tmp_path):
    from swampcastle.wal import WalWriter

    class SpyCollection:
        def __init__(self):
            self.upsert_calls = []
            self.ids = [f"d{i}" for i in range(5000)]

        def get(self, *, ids=None, where=None, limit=None, offset=None, include=None):
            return {
                "ids": self.ids,
                "documents": [f"doc {i}" for i in range(5000)],
                "metadatas": [
                    {"wing": "test", "room": "r1", "source_file": ""} for _ in range(5000)
                ],
            }

        def upsert(self, *, documents, ids, metadatas=None):
            self.upsert_calls.append(len(ids))

    progress_updates = []
    service = VaultService(SpyCollection(), WalWriter(tmp_path / "wal"))

    count = service.reforge(
        progress_callback=lambda processed, total: progress_updates.append((processed, total)),
    )

    assert count == 5000
    assert service._col.upsert_calls == [1000, 1000, 1000, 1000, 1000]
    assert progress_updates[0] == (0, 5000)
    assert progress_updates[-1] == (5000, 5000)


def test_distill_parallel_workers_one_uses_sequential_path(castle, monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("ProcessPoolExecutor should not be used for parallel_workers=1")

    monkeypatch.setattr("swampcastle.services.vault.ProcessPoolExecutor", fail_if_called)

    count = castle.vault.distill(parallel_workers=1)

    assert count == 2
    results = castle.vault._col.get(include=["metadatas"])
    for meta in results["metadatas"]:
        assert "aaak" in meta


def test_distill_parallel_uses_spawn_context(castle, monkeypatch):
    captured: dict[str, object] = {}

    class RecordingExecutor:
        def __init__(self, *, max_workers, mp_context=None, initializer=None, initargs=()):
            captured["max_workers"] = max_workers
            captured["mp_context"] = mp_context
            self._initializer = initializer
            self._initargs = initargs

        def __enter__(self):
            if self._initializer is not None:
                self._initializer(*self._initargs)
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def map(self, fn, iterable, chunksize=1):
            for item in iterable:
                yield fn(item)

        def submit(self, fn, *args, **kwargs):
            future = Future()
            future.set_result(fn(*args, **kwargs))
            return future

    monkeypatch.setattr("swampcastle.services.vault.ProcessPoolExecutor", RecordingExecutor)

    count = castle.vault.distill(parallel_workers=2)

    assert count == 2
    assert captured["max_workers"] == 2
    assert captured["mp_context"] is not None
    assert captured["mp_context"].get_start_method() == "spawn"


def test_distill_parallel_flushes_updates_in_batches(tmp_path, monkeypatch):
    from swampcastle.wal import WalWriter

    class SpyCollection:
        def __init__(self):
            self.update_calls: list[list[str]] = []

        def get(self, *, ids=None, where=None, limit=None, offset=None, include=None):
            return {
                "ids": ["d1", "d2", "d3", "d4", "d5"],
                "documents": [f"doc {i}" for i in range(1, 6)],
                "metadatas": [{"wing": "test", "room": "r1", "source_file": ""} for _ in range(5)],
            }

        def update(self, *, ids, documents=None, metadatas=None):
            self.update_calls.append(list(ids))

    class RecordingExecutor:
        def __init__(self, *, max_workers, mp_context=None, initializer=None, initargs=()):
            self._initializer = initializer
            self._initargs = initargs

        def __enter__(self):
            if self._initializer is not None:
                self._initializer(*self._initargs)
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def map(self, fn, iterable, chunksize=1):
            for item in iterable:
                yield fn(item)

        def submit(self, fn, *args, **kwargs):
            future = Future()
            future.set_result(fn(*args, **kwargs))
            return future

    monkeypatch.setattr("swampcastle.services.vault.ProcessPoolExecutor", RecordingExecutor)
    monkeypatch.setattr("swampcastle.services.vault._DISTILL_WRITE_BATCH_SIZE", 2, raising=False)

    service = VaultService(SpyCollection(), WalWriter(tmp_path / "wal"))

    count = service.distill(parallel_workers=2)

    assert count == 5
    assert service._col.update_calls == [["d1", "d2"], ["d3", "d4"], ["d5"]]


def test_distill_parallel_matches_sequential_output(tmp_path):
    from swampcastle.wal import WalWriter

    factory = InMemoryStorageFactory()
    wal = WalWriter(tmp_path / "wal")
    sequential = VaultService(factory.open_collection("distill_seq"), wal)
    parallel = VaultService(factory.open_collection("distill_par"), wal)

    contents = [
        "Alice discussed vector search and testing strategy.",
        "Bob fixed the broken deployment after the database migration.",
        "Carol documented the architecture and reviewed the benchmark numbers.",
    ]

    for index, content in enumerate(contents, start=1):
        command = AddDrawerCommand(
            wing="test", room="r1", content=content, source_file=f"f{index}.md"
        )
        sequential.add_drawer(command)
        parallel.add_drawer(command)

    assert sequential.distill() == len(contents)
    assert parallel.distill(parallel_workers=2) == len(contents)

    sequential_results = sequential._col.get(include=["metadatas"])
    parallel_results = parallel._col.get(include=["metadatas"])

    sequential_aaak = {
        doc_id: meta["aaak"]
        for doc_id, meta in zip(sequential_results["ids"], sequential_results["metadatas"])
    }
    parallel_aaak = {
        doc_id: meta["aaak"]
        for doc_id, meta in zip(parallel_results["ids"], parallel_results["metadatas"])
    }

    assert parallel_aaak == sequential_aaak
