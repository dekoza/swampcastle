"""Direct tests for swampcastle.cli.commands."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from swampcastle.cli import commands


@pytest.fixture(autouse=True)
def restore_castle_env(monkeypatch, tmp_path):
    original = os.environ.get("SWAMPCASTLE_CASTLE_PATH")
    monkeypatch.setattr("swampcastle.runtime_config.Path.home", lambda: tmp_path)
    yield
    if original is None:
        monkeypatch.delenv("SWAMPCASTLE_CASTLE_PATH", raising=False)
    else:
        monkeypatch.setenv("SWAMPCASTLE_CASTLE_PATH", original)


class DummyCastle:
    def __init__(
        self, settings, factory, *, status=None, search=None, distill_count=0, reforge_count=0
    ):
        self.catalog = SimpleNamespace(status=lambda: status)
        self.search = SimpleNamespace(search=lambda query: search)
        self.vault = SimpleNamespace(
            distill=lambda **kwargs: distill_count,
            reforge=lambda **kwargs: reforge_count,
        )
        self._collection = object()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def test_settings_uses_palace_and_backend(tmp_path):
    args = SimpleNamespace(palace="/tmp/castle", backend="postgres")
    settings = commands._settings(args)
    assert str(settings.castle_path) == "/tmp/castle"
    assert settings.backend == "postgres"
    assert (tmp_path / ".swampcastle" / "config.json").exists()


def test_cmd_survey_prints_status(capsys):
    status = SimpleNamespace(total_drawers=3, wings={"a": 1}, rooms={"r": 1})

    with patch("swampcastle.castle.Castle", lambda s, f: DummyCastle(s, f, status=status)):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_survey(SimpleNamespace(palace=None, backend=None))

    out = capsys.readouterr().out
    assert "SwampCastle Survey" in out
    assert "Drawers: 3" in out
    assert "a" in out
    assert "r" in out


def test_cmd_seek_prints_no_results(capsys):
    result = SimpleNamespace(results=[])
    args = SimpleNamespace(
        query="nothing", wing=None, room=None, results=5, palace=None, backend=None
    )

    with patch("swampcastle.castle.Castle", lambda s, f: DummyCastle(s, f, search=result)):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_seek(args)

    out = capsys.readouterr().out
    assert "SwampCastle Seek" in out
    assert "No results" in out


def test_cmd_seek_prints_hits(capsys):
    hit = SimpleNamespace(wing="proj", room="auth", similarity=0.9, text="hello world")
    result = SimpleNamespace(results=[hit])
    args = SimpleNamespace(
        query="hello", wing=None, room=None, results=5, palace=None, backend=None
    )

    with patch("swampcastle.castle.Castle", lambda s, f: DummyCastle(s, f, search=result)):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_seek(args)

    out = capsys.readouterr().out
    assert "SwampCastle Seek" in out
    assert "Results: 1" in out
    assert "proj / auth" in out
    assert "hello world" in out


def test_cmd_project_exits_for_missing_dir(capsys):
    with pytest.raises(SystemExit, match="1"):
        commands.cmd_project(
            SimpleNamespace(dir="/does/not/exist", yes=False, palace=None, backend=None)
        )
    assert "not a directory" in capsys.readouterr().out


def test_cmd_project_prints_detection_summary(tmp_path, capsys):
    project = tmp_path / "project"
    project.mkdir()
    args = SimpleNamespace(dir=str(project), yes=False, palace=None, backend=None, wing=None)

    with patch("swampcastle.mining.rooms.detect_rooms_local") as mock_detect_rooms:
        commands.cmd_project(args)

    mock_detect_rooms.assert_called_once_with(str(project), yes=False, wing=None, team=None)


def test_cmd_project_calls_real_room_detector_signature(tmp_path, capsys):
    project = tmp_path / "project"
    (project / "backend").mkdir(parents=True)
    (project / "backend" / "app.py").write_text("print('hello')\n")
    args = SimpleNamespace(dir=str(project), yes=True, palace=None, backend=None, wing=None)

    commands.cmd_project(args)

    out = capsys.readouterr().out
    assert "Config saved:" in out
    assert "swampcastle gather" in out


def test_cmd_project_creates_swampcastle_yaml(tmp_path):
    project = tmp_path / "project"
    (project / "backend").mkdir(parents=True)
    (project / "backend" / "app.py").write_text("print('hello')\n")
    args = SimpleNamespace(dir=str(project), yes=True, palace=None, backend=None, wing=None)

    commands.cmd_project(args)

    assert (project / ".swampcastle.yaml").exists()


def test_cmd_gather_projects_uses_miner(tmp_path, capsys):
    target = tmp_path / "proj"
    target.mkdir()
    args = SimpleNamespace(
        dir=str(target),
        mode="projects",
        wing="wing1",
        agent="swampcastle",
        dry_run=False,
        no_gitignore=False,
        include_ignored=["*.log"],
        limit=7,
        palace=None,
        backend=None,
    )

    with patch("swampcastle.cli.commands.factory_from_settings", return_value="factory"):
        with patch("swampcastle.mining.miner.mine") as mock_mine:
            commands.cmd_gather(args)

    out = capsys.readouterr().out
    assert "SwampCastle Gather" in out
    assert mock_mine.call_args.kwargs["storage_factory"] == "factory"
    assert mock_mine.call_args.kwargs["include_ignored"] == ["*.log"]


def test_cmd_gather_convos_uses_convo_miner_in_dry_run(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    args = SimpleNamespace(
        dir=str(target),
        mode="convos",
        wing="wing1",
        agent="agentx",
        dry_run=True,
        extract="exchange",
        limit=3,
        palace=None,
        backend=None,
    )

    with patch("swampcastle.mining.convo.mine_convos") as mock_mine:
        commands.cmd_gather(args)

    assert mock_mine.call_args.kwargs["storage_factory"] is None
    assert mock_mine.call_args.kwargs["extract_mode"] == "exchange"


def test_cmd_herald_prints_protocol_only(capsys):
    status = SimpleNamespace(protocol="L0+L1", wings={"alpha": 1}, total_drawers=5)

    with patch("swampcastle.castle.Castle", lambda s, f: DummyCastle(s, f, status=status)):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_herald(SimpleNamespace(palace=None, backend=None))

    out = capsys.readouterr().out
    assert "L0+L1" in out
    assert "Total: 5 drawers" not in out
    assert "Wings:" not in out


def test_cmd_brief_prints_wing_summary(capsys):
    brief = SimpleNamespace(
        wing="proj",
        total_drawers=3,
        rooms={"auth": 2, "billing": 1},
        contributors={"dekoza": 2, "sarah": 1},
        source_files=2,
        error=None,
    )

    class BriefCastle(DummyCastle):
        def __init__(self, settings, factory):
            super().__init__(settings, factory, status=None)
            self.catalog = SimpleNamespace(brief=lambda wing: brief)

    args = SimpleNamespace(wing="proj", palace=None, backend=None)
    with patch("swampcastle.castle.Castle", BriefCastle):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_brief(args)

    out = capsys.readouterr().out
    assert "SwampCastle Brief" in out
    assert "Wing: proj" in out
    assert "Drawers: 3" in out
    assert "Files: 2" in out
    assert "auth (2)" in out
    assert "dekoza (2)" in out


def test_cmd_cleave_passes_argv_without_mutating_sys_argv(tmp_path):
    args = SimpleNamespace(dir=str(tmp_path), output_dir="/tmp/out", dry_run=True, min_sessions=4)
    original_argv = list(os.sys.argv)

    with patch("swampcastle.split_mega_files.main") as mock_main:
        commands.cmd_cleave(args)

    assert os.sys.argv == original_argv
    mock_main.assert_called_once_with(
        [
            str(tmp_path),
            "--output-dir",
            "/tmp/out",
            "--dry-run",
            "--min-sessions",
            "4",
        ]
    )


def test_cmd_distill_prints_no_drawers(capsys):
    args = SimpleNamespace(
        wing=None, room=None, dry_run=False, config=None, palace=None, backend=None
    )

    with patch("swampcastle.castle.Castle", lambda s, f: DummyCastle(s, f, distill_count=0)):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_distill(args)

    assert "No drawers to distill" in capsys.readouterr().out


def test_cmd_distill_passes_config_and_dry_run(capsys):
    class DistillCastle(DummyCastle):
        def __init__(self, settings, factory):
            self.calls = []
            self.catalog = SimpleNamespace(status=lambda: None)
            self.search = SimpleNamespace(search=lambda q: None)
            self.vault = SimpleNamespace(distill=lambda **kwargs: self.calls.append(kwargs) or 2)
            self._collection = object()

    castle = DistillCastle(None, None)
    args = SimpleNamespace(
        wing="w", room="r", dry_run=True, config="entities.json", palace=None, backend=None
    )

    with patch("swampcastle.castle.Castle", lambda s, f: castle):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_distill(args)

    assert castle.calls == [
        {"wing": "w", "room": "r", "dry_run": True, "config_path": "entities.json"}
    ]
    assert "DRY RUN" in capsys.readouterr().out


def test_cmd_wizard_runs_runtime_wizard():
    with patch("swampcastle.wizard.run_wizard") as mock:
        commands.cmd_wizard(SimpleNamespace())
    mock.assert_called_once_with()


def test_cmd_drawbridge_setup_prints_examples(capsys):
    commands.cmd_drawbridge_setup(SimpleNamespace(palace=None))
    out = capsys.readouterr().out
    assert "claude mcp add swampcastle" in out
    assert "/path/to/castle" in out


def test_cmd_drawbridge_run_sets_env_and_calls_server(tmp_path):
    palace = tmp_path / "castle"
    with patch("swampcastle.mcp.server.main") as mock_main:
        commands.cmd_drawbridge_run(SimpleNamespace(run_palace=str(palace), palace=None))
    assert os.environ["SWAMPCASTLE_CASTLE_PATH"] == str(palace.resolve())
    mock_main.assert_called_once()


def test_cmd_reforge_updates_embedder_settings_and_prints(capsys):
    class ReforgeCastle(DummyCastle):
        def __init__(self, settings, factory):
            self.calls = []
            self.catalog = SimpleNamespace(status=lambda: None)
            self.search = SimpleNamespace(search=lambda q: None)
            self.vault = SimpleNamespace(reforge=lambda **kwargs: self.calls.append(kwargs) or 3)
            self._collection = object()

    castle = ReforgeCastle(None, None)
    args = SimpleNamespace(
        wing="w", room="r", dry_run=False, embedder="onnx", device="cpu", palace=None, backend=None
    )

    with patch("swampcastle.castle.Castle", lambda s, f: castle):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_reforge(args)

    assert castle.calls == [{"wing": "w", "room": "r", "dry_run": False}]
    assert "onnx embedder" in capsys.readouterr().out


def test_cmd_armory_lists_models(capsys):
    with patch(
        "swampcastle.embeddings.list_embedders",
        return_value=[
            {
                "name": "all-MiniLM-L6-v2",
                "alias": "minilm",
                "dim": 384,
                "backend": "onnx",
                "notes": "Default.",
            }
        ],
    ):
        commands.cmd_armory(SimpleNamespace())

    out = capsys.readouterr().out
    assert "all-MiniLM-L6-v2" in out
    assert "minilm" in out
    assert "onnx" in out


def test_cmd_garrison_exits_when_uvicorn_missing(capsys):
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "uvicorn":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        with pytest.raises(SystemExit, match="1"):
            commands.cmd_garrison(
                SimpleNamespace(host="0.0.0.0", port=7433, palace=None, backend=None)
            )

    assert "Sync server requires" in capsys.readouterr().out


def test_cmd_garrison_runs_uvicorn(monkeypatch):
    uvicorn = SimpleNamespace(run=lambda app, host, port: None)
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", uvicorn)
    with patch("swampcastle.sync_server.create_app", return_value="app"):
        with patch.object(uvicorn, "run") as mock_run:
            commands.cmd_garrison(
                SimpleNamespace(host="127.0.0.1", port=9999, palace="/tmp/castle", backend=None)
            )
    assert os.environ["SWAMPCASTLE_CASTLE_PATH"] == "/tmp/castle"
    mock_run.assert_called_once_with("app", host="127.0.0.1", port=9999)


def test_cmd_parley_dry_run(capsys):
    class ParleyCastle(DummyCastle):
        def __init__(self, settings, factory):
            self._collection = object()
            self.catalog = None
            self.search = None
            self.vault = None

    with patch("swampcastle.castle.Castle", lambda s, f: ParleyCastle(s, f)):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            with patch("swampcastle.sync.SyncEngine"):
                with patch("swampcastle.sync_client.SyncClient") as mock_client:
                    with patch("swampcastle.sync_meta.NodeIdentity"):
                        commands.cmd_parley(
                            SimpleNamespace(
                                server="http://x", dry_run=True, palace=None, backend=None
                            )
                        )

    out = capsys.readouterr().out
    assert "SwampCastle Sync" in out
    assert "Server: http://x" in out
    assert "DRY RUN" in out
    mock_client.assert_called_once_with("http://x")


def test_cmd_parley_live_prints_summary(capsys):
    class ParleyCastle(DummyCastle):
        def __init__(self, settings, factory):
            self._collection = object()
            self.catalog = None
            self.search = None
            self.vault = None

    client = SimpleNamespace(sync=lambda engine: {"push": {"sent": 2}, "pull": {"received": 3}})
    with patch("swampcastle.castle.Castle", lambda s, f: ParleyCastle(s, f)):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            with patch("swampcastle.sync.SyncEngine"):
                with patch("swampcastle.sync_client.SyncClient", return_value=client):
                    with patch("swampcastle.sync_meta.NodeIdentity"):
                        commands.cmd_parley(
                            SimpleNamespace(
                                server="http://x", dry_run=False, palace=None, backend=None
                            )
                        )

    out = capsys.readouterr().out
    assert "SwampCastle Sync" in out
    assert "Server: http://x" in out
    assert "Pushed: 2" in out
    assert "Pulled: 3" in out


def test_cmd_parley_uses_config_dir_for_identity(tmp_path):
    class ParleyCastle(DummyCastle):
        def __init__(self, settings, factory):
            self._collection = object()
            self.catalog = None
            self.search = None
            self.vault = None

    palace = tmp_path / "castle"
    args = SimpleNamespace(server="http://x", dry_run=True, palace=str(palace), backend=None)

    with patch("swampcastle.castle.Castle", lambda s, f: ParleyCastle(s, f)):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            with patch("swampcastle.sync.SyncEngine"):
                with patch("swampcastle.sync_client.SyncClient"):
                    with patch("swampcastle.sync_meta.NodeIdentity") as mock_identity:
                        commands.cmd_parley(args)

    mock_identity.assert_called_once_with(config_dir=str(palace.parent))


def test_cmd_ni_prints_easter_egg(capsys):
    commands.cmd_ni(SimpleNamespace())
    assert "Ni!" in capsys.readouterr().out


def test_cmd_seek_prints_contributor_filter_and_hit(capsys):
    hit = SimpleNamespace(
        wing="proj",
        room="auth",
        similarity=0.9,
        text="hello world",
        contributor="dekoza",
    )
    result = SimpleNamespace(results=[hit])
    args = SimpleNamespace(
        query="hello",
        wing=None,
        room=None,
        contributor="dekoza",
        results=5,
        palace=None,
        backend=None,
    )

    with patch("swampcastle.castle.Castle", lambda s, f: DummyCastle(s, f, search=result)):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_seek(args)

    out = capsys.readouterr().out
    assert "Contributor: dekoza" in out
    assert "by dekoza" in out


def test_cmd_deskeleton_pages_drawers_in_batches(capsys):
    class PaginatedVault:
        def __init__(self):
            self.calls = []

        def get_drawers(self, **kwargs):
            self.calls.append(kwargs)
            offset = kwargs.get("offset", 0)
            limit = kwargs.get("limit")
            if offset == 0:
                return {
                    "ids": [f"d{i}" for i in range(limit)],
                    "metadatas": [
                        {
                            "wing": "alpha",
                            "source_file": "/tmp/one.py",
                            "is_skeleton": True,
                        }
                        for _ in range(limit)
                    ],
                }
            if offset == limit:
                return {
                    "ids": ["tail"],
                    "metadatas": [
                        {
                            "wing": "beta",
                            "source_file": "/tmp/two.py",
                            "is_skeleton": True,
                        }
                    ],
                }
            return {"ids": [], "metadatas": []}

    vault = PaginatedVault()

    class DeskeletonCastle:
        def __init__(self, settings, factory):
            self.vault = vault

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    args = SimpleNamespace(
        palace="/tmp/castle",
        backend=None,
        wing=None,
        room=None,
        dry_run=True,
    )

    with patch("swampcastle.castle.Castle", DeskeletonCastle):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_deskeleton(args)

    assert len(vault.calls) == 2
    assert vault.calls[0]["limit"] == 1000
    assert vault.calls[0]["offset"] == 0
    assert vault.calls[1]["limit"] == 1000
    assert vault.calls[1]["offset"] == 1000

    out = capsys.readouterr().out
    assert "/tmp/one.py" in out
    assert "/tmp/two.py" in out


def test_deskeleton_target_store_dedupes_on_disk(tmp_path):
    store = commands.DeskeletonTargetStore(tmp_path / "targets.sqlite3")
    try:
        assert store.add("alpha", "/tmp/one.py") is True
        assert store.add("alpha", "/tmp/one.py") is False
        assert store.add("beta", "/tmp/two.py") is True
        assert store.count() == 2
        assert list(store.iter_targets()) == [
            ("alpha", "/tmp/one.py"),
            ("beta", "/tmp/two.py"),
        ]
    finally:
        store.close()


def test_scan_deskeleton_targets_stores_unique_targets_per_page(tmp_path):
    class PaginatedVault:
        def __init__(self):
            self.calls = []

        def get_drawers(self, **kwargs):
            self.calls.append(kwargs)
            offset = kwargs.get("offset", 0)
            limit = kwargs.get("limit")
            if offset == 0:
                return {
                    "ids": [f"d{i}" for i in range(limit)],
                    "metadatas": [
                        {
                            "wing": "alpha",
                            "source_file": "/tmp/one.py",
                            "is_skeleton": True,
                        }
                        for _ in range(limit)
                    ],
                }
            if offset == limit:
                return {
                    "ids": ["dup", "tail"],
                    "metadatas": [
                        {
                            "wing": "alpha",
                            "source_file": "/tmp/one.py",
                            "is_skeleton": True,
                        },
                        {
                            "wing": "beta",
                            "source_file": "/tmp/two.py",
                            "is_skeleton": True,
                        },
                    ],
                }
            return {"ids": [], "metadatas": []}

    vault = PaginatedVault()
    store = commands.DeskeletonTargetStore(tmp_path / "targets.sqlite3")
    try:
        skeleton_count, unique_count = commands._scan_deskeleton_targets(
            vault,
            None,
            store,
            batch_size=1000,
        )

        assert skeleton_count == 1002
        assert unique_count == 2
        assert len(vault.calls) == 2
        assert vault.calls[0]["offset"] == 0
        assert vault.calls[1]["offset"] == 1000
        assert list(store.iter_targets()) == [
            ("alpha", "/tmp/one.py"),
            ("beta", "/tmp/two.py"),
        ]
    finally:
        store.close()
