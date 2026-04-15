import tempfile
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

import yaml

from swampcastle.mining.miner import _resolve_parallel_workers, mine
from swampcastle.storage.memory import InMemoryStorageFactory


def write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# _resolve_parallel_workers unit tests
# ---------------------------------------------------------------------------


def test_resolve_sequential_by_default(monkeypatch):
    monkeypatch.delenv("SWAMPCASTLE_PARALLEL", raising=False)
    monkeypatch.delenv("SWAMPCASTLE_PARALLEL_WORKERS", raising=False)
    assert _resolve_parallel_workers(None) is None


def test_resolve_explicit_arg(monkeypatch):
    monkeypatch.delenv("SWAMPCASTLE_PARALLEL", raising=False)
    assert _resolve_parallel_workers(4) == 4


def test_resolve_explicit_arg_capped():
    assert _resolve_parallel_workers(9999) == 32


def test_resolve_explicit_zero_means_sequential():
    assert _resolve_parallel_workers(0) is None


def test_resolve_explicit_one_means_sequential():
    assert _resolve_parallel_workers(1) is None


def test_resolve_env_var(monkeypatch):
    monkeypatch.setenv("SWAMPCASTLE_PARALLEL", "1")
    monkeypatch.setenv("SWAMPCASTLE_PARALLEL_WORKERS", "6")
    assert _resolve_parallel_workers(None) == 6


def test_resolve_env_var_capped(monkeypatch):
    monkeypatch.setenv("SWAMPCASTLE_PARALLEL", "true")
    monkeypatch.setenv("SWAMPCASTLE_PARALLEL_WORKERS", "9999")
    assert _resolve_parallel_workers(None) == 32


def test_resolve_explicit_beats_env(monkeypatch):
    monkeypatch.setenv("SWAMPCASTLE_PARALLEL", "1")
    monkeypatch.setenv("SWAMPCASTLE_PARALLEL_WORKERS", "8")
    assert _resolve_parallel_workers(3) == 3


# ---------------------------------------------------------------------------
# parallel mine integration tests
# ---------------------------------------------------------------------------


def _make_project(project_root: Path, *, wing: str = "parallel_test"):
    write_file(project_root / "a.py", "def alpha():\n    pass\n" * 20)
    write_file(project_root / "b.txt", "hello world\n" * 50)
    write_file(project_root / "sub" / "c.md", "# Notes\n\nSome content here.\n" * 30)
    with open(project_root / ".swampcastle.yaml", "w") as f:
        yaml.dump(
            {
                "wing": wing,
                "rooms": [
                    {"name": "code", "description": "Source code", "keywords": ["def", "class"]},
                    {
                        "name": "docs",
                        "description": "Documentation",
                        "keywords": ["notes", "readme"],
                    },
                    {"name": "general", "description": "General"},
                ],
            },
            f,
        )


def test_mine_parallel_produces_same_drawers_as_sequential():
    """Parallel and sequential paths must produce the same drawer count."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        factory_seq = InMemoryStorageFactory()
        _make_project(root / "seq", wing="seq_wing")
        mine(str(root / "seq"), str(root / "palace_seq"), storage_factory=factory_seq)

        factory_par = InMemoryStorageFactory()
        _make_project(root / "par", wing="par_wing")
        mine(
            str(root / "par"),
            str(root / "palace_par"),
            storage_factory=factory_par,
            parallel_workers=2,
        )

        col_seq = factory_seq.open_collection("swampcastle_chests")
        col_par = factory_par.open_collection("swampcastle_chests")
        assert col_seq.count() == col_par.count()


def test_mine_parallel_metadata_correctness():
    """Every drawer must carry the correct wing, room and source_file metadata."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        _make_project(root, wing="meta_test")
        factory = InMemoryStorageFactory()
        mine(str(root), str(root / "palace"), storage_factory=factory, parallel_workers=2)

        col = factory.open_collection("swampcastle_chests")
        rows = col.get(include=["metadatas"])
        assert rows["metadatas"], "no drawers were stored"

        for meta in rows["metadatas"]:
            assert meta["wing"] == "meta_test", f"wrong wing: {meta['wing']}"
            assert meta["room"] in {"code", "docs", "general"}, f"unknown room: {meta['room']}"
            assert Path(meta["source_file"]).exists(), f"source_file missing: {meta['source_file']}"
            assert "source_mtime" in meta, "source_mtime not stored"
            assert "chunk_index" in meta, "chunk_index not stored"


def test_mine_parallel_contributor_metadata():
    """contributor field must be populated when a team is configured."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        write_file(root / "code.py", "x = 1\n" * 20)
        with open(root / ".swampcastle.yaml", "w") as f:
            yaml.dump(
                {
                    "wing": "contrib_test",
                    "team": ["alice", "bob"],
                    "rooms": [{"name": "general", "description": "General"}],
                },
                f,
            )
        factory = InMemoryStorageFactory()
        with patch("swampcastle.mining.contributor._git_last_author", return_value="alice"):
            mine(str(root), str(root / "palace"), storage_factory=factory, parallel_workers=2)

        col = factory.open_collection("swampcastle_chests")
        rows = col.get(include=["metadatas"])
        assert all(m.get("contributor") == "alice" for m in rows["metadatas"])


def test_mine_parallel_skips_already_mined_files():
    """A file already in the collection with a matching mtime must not be re-added."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        _make_project(root, wing="skip_test")
        factory = InMemoryStorageFactory()

        mine(str(root), str(root / "palace"), storage_factory=factory, parallel_workers=2)
        col = factory.open_collection("swampcastle_chests")
        count_after_first = col.count()

        mine(str(root), str(root / "palace"), storage_factory=factory, parallel_workers=2)
        assert col.count() == count_after_first, "already-mined files were re-added"


def test_mine_parallel_env_var(monkeypatch):
    """SWAMPCASTLE_PARALLEL env var activates the parallel path without explicit arg."""
    monkeypatch.setenv("SWAMPCASTLE_PARALLEL", "1")
    monkeypatch.setenv("SWAMPCASTLE_PARALLEL_WORKERS", "2")
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        _make_project(root, wing="env_test")
        factory = InMemoryStorageFactory()
        mine(str(root), str(root / "palace"), storage_factory=factory)
        col = factory.open_collection("swampcastle_chests")
        assert col.count() > 0


def test_mine_reports_progress_sequential():
    progress_updates = []

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        _make_project(root, wing="progress_seq")

        mine(
            str(root),
            str(root / "palace"),
            dry_run=True,
            progress_callback=lambda processed, total: progress_updates.append((processed, total)),
        )

    assert progress_updates[0] == (0, 4)
    assert progress_updates[-1] == (4, 4)
    assert [processed for processed, _ in progress_updates] == sorted(
        processed for processed, _ in progress_updates
    )


def test_mine_reports_progress_parallel():
    progress_updates = []

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        _make_project(root, wing="progress_par")

        mine(
            str(root),
            str(root / "palace"),
            dry_run=True,
            parallel_workers=2,
            progress_callback=lambda processed, total: progress_updates.append((processed, total)),
        )

    assert progress_updates[0] == (0, 4)
    assert progress_updates[-1] == (4, 4)
    assert [processed for processed, _ in progress_updates] == sorted(
        processed for processed, _ in progress_updates
    )


def test_mine_parallel_progress_counts_already_mined_files():
    progress_updates = []

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        _make_project(root, wing="progress_skip")
        factory = InMemoryStorageFactory()

        mine(str(root), str(root / "palace"), storage_factory=factory, parallel_workers=2)
        mine(
            str(root),
            str(root / "palace"),
            storage_factory=factory,
            parallel_workers=2,
            progress_callback=lambda processed, total: progress_updates.append((processed, total)),
        )

    assert progress_updates[0] == (0, 4)
    assert progress_updates[-1] == (4, 4)


def test_mine_parallel_workers_one_uses_sequential_path(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("ProcessPoolExecutor should not be used for parallel_workers=1")

    monkeypatch.setattr("swampcastle.mining.miner.ProcessPoolExecutor", fail_if_called)

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        _make_project(root, wing="workers_one_test")
        mine(str(root), str(root / "palace"), dry_run=True, parallel_workers=1)


def test_mine_parallel_uses_spawn_context(monkeypatch):
    captured: dict[str, object] = {}

    class RecordingExecutor:
        def __init__(self, *, max_workers, mp_context=None):
            captured["max_workers"] = max_workers
            captured["mp_context"] = mp_context

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args, **kwargs):
            future = Future()
            future.set_result(fn(*args, **kwargs))
            return future

    monkeypatch.setattr("swampcastle.mining.miner.ProcessPoolExecutor", RecordingExecutor)

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        _make_project(root, wing="spawn_test")
        mine(str(root), str(root / "palace"), dry_run=True, parallel_workers=2)

    assert captured["max_workers"] == 2
    assert captured["mp_context"] is not None
    assert captured["mp_context"].get_start_method() == "spawn"
