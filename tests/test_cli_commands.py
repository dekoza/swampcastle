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
        extract_kg_proposals=True,
        palace=None,
        backend=None,
    )
    settings = SimpleNamespace(castle_path=tmp_path / "castle", embed_batch_size=128)

    with patch("swampcastle.cli.commands._settings", return_value=settings):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value="factory"):
            with patch("swampcastle.mining.miner.mine") as mock_mine:
                commands.cmd_gather(args)

    out = capsys.readouterr().out
    assert "SwampCastle Gather" in out
    assert mock_mine.call_args.kwargs["storage_factory"] == "factory"
    assert mock_mine.call_args.kwargs["include_ignored"] == ["*.log"]
    assert mock_mine.call_args.kwargs["extract_kg_proposals"] is True
    assert mock_mine.call_args.kwargs["embed_batch_size"] == 128
    assert mock_mine.call_args.kwargs["progress_callback"] is None
    assert callable(mock_mine.call_args.kwargs["phase_progress_callback"])


def test_cmd_gather_exits_cleanly_on_keyboard_interrupt(tmp_path, capsys):
    target = tmp_path / "proj"
    target.mkdir()
    args = SimpleNamespace(
        dir=str(target),
        mode="projects",
        wing="wing1",
        agent="swampcastle",
        dry_run=False,
        no_gitignore=False,
        include_ignored=[],
        limit=0,
        extract_kg_proposals=False,
        palace=None,
        backend=None,
    )
    settings = SimpleNamespace(castle_path=tmp_path / "castle", embed_batch_size=128)

    closed = {"called": False}

    class DummyFactory:
        def close(self):
            closed["called"] = True

    with patch("swampcastle.cli.commands._settings", return_value=settings):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=DummyFactory()):
            with patch("swampcastle.mining.miner.mine", side_effect=KeyboardInterrupt):
                with pytest.raises(SystemExit) as exc:
                    commands.cmd_gather(args)

    assert exc.value.code == 130
    assert closed["called"] is True
    out = capsys.readouterr().out
    assert "Cancelled by user" in out


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
        extract_kg_proposals=True,
        palace=None,
        backend=None,
    )

    with patch("swampcastle.mining.convo.mine_convos") as mock_mine:
        commands.cmd_gather(args)

    assert mock_mine.call_args.kwargs["storage_factory"] is None
    assert mock_mine.call_args.kwargs["extract_mode"] == "exchange"
    assert mock_mine.call_args.kwargs["extract_kg_proposals"] is True


def test_cmd_gather_projects_renders_progress_bar(tmp_path, capsys):
    target = tmp_path / "proj"
    target.mkdir()
    args = SimpleNamespace(
        dir=str(target),
        mode="projects",
        wing="wing1",
        agent="swampcastle",
        dry_run=False,
        no_gitignore=False,
        include_ignored=[],
        limit=0,
        extract_kg_proposals=False,
        palace=None,
        backend=None,
    )
    settings = SimpleNamespace(castle_path=tmp_path / "castle", embed_batch_size=128)

    def fake_mine(*args, **kwargs):
        phase_progress_callback = kwargs["phase_progress_callback"]
        phase_progress_callback("mine", 0, 3)
        phase_progress_callback("mine", 3, 3)
        phase_progress_callback("flush", 0, 2)
        phase_progress_callback("flush", 2, 2)

    with patch("swampcastle.cli.commands._settings", return_value=settings):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value="factory"):
            with patch("swampcastle.mining.miner.mine", side_effect=fake_mine):
                commands.cmd_gather(args)

    out = capsys.readouterr().out
    assert "Mining" in out
    assert "3/3" in out
    assert "Flushing" in out
    assert "2/2" in out


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
        wing=None,
        room=None,
        dry_run=False,
        apply=False,
        config=None,
        palace=None,
        backend=None,
    )

    with patch("swampcastle.castle.Castle", lambda s, f: DummyCastle(s, f, distill_count=0)):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_distill(args)

    assert "No drawers to distill" in capsys.readouterr().out


def test_cmd_distill_defaults_to_preview_mode(capsys):
    class DistillCastle(DummyCastle):
        def __init__(self, settings, factory):
            self.calls = []
            self.catalog = SimpleNamespace(status=lambda: None)
            self.search = SimpleNamespace(search=lambda q: None)
            self.vault = SimpleNamespace(distill=lambda **kwargs: self.calls.append(kwargs) or 2)
            self._collection = object()

    castle = DistillCastle(None, None)
    args = SimpleNamespace(
        wing="w", room="r", dry_run=False, apply=False, config=None, palace=None, backend=None
    )

    with patch("swampcastle.castle.Castle", lambda s, f: castle):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_distill(args)

    assert castle.calls == [
        {
            "wing": "w",
            "room": "r",
            "dry_run": True,
            "config_path": None,
            "progress_callback": None,
            "phase_progress_callback": None,
        }
    ]
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "--apply" in out


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
        wing="w",
        room="r",
        dry_run=True,
        apply=False,
        config="entities.json",
        palace=None,
        backend=None,
    )

    with patch("swampcastle.castle.Castle", lambda s, f: castle):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_distill(args)

    assert castle.calls == [
        {
            "wing": "w",
            "room": "r",
            "dry_run": True,
            "config_path": "entities.json",
            "progress_callback": None,
            "phase_progress_callback": None,
        }
    ]
    assert "DRY RUN" in capsys.readouterr().out


def test_cmd_distill_apply_enables_real_write(capsys):
    class DistillCastle(DummyCastle):
        def __init__(self, settings, factory):
            self.calls = []
            self.catalog = SimpleNamespace(status=lambda: None)
            self.search = SimpleNamespace(search=lambda q: None)
            self.vault = SimpleNamespace(distill=lambda **kwargs: self.calls.append(kwargs) or 2)
            self._collection = object()

    castle = DistillCastle(None, None)
    args = SimpleNamespace(
        wing="w", room="r", dry_run=False, apply=True, config=None, palace=None, backend=None
    )

    with patch("swampcastle.castle.Castle", lambda s, f: castle):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_distill(args)

    assert castle.calls[0]["wing"] == "w"
    assert castle.calls[0]["room"] == "r"
    assert castle.calls[0]["dry_run"] is False
    assert castle.calls[0]["config_path"] is None
    assert castle.calls[0]["progress_callback"] is None
    assert callable(castle.calls[0]["phase_progress_callback"])
    assert "Distilled 2 drawers with AAAK dialect." in capsys.readouterr().out


def test_cmd_distill_renders_progress_bar(capsys):
    class DistillCastle(DummyCastle):
        def __init__(self, settings, factory):
            self.calls = []
            self.catalog = SimpleNamespace(status=lambda: None)
            self.search = SimpleNamespace(search=lambda q: None)

            def distill(**kwargs):
                self.calls.append(kwargs)
                phase_progress_callback = kwargs["phase_progress_callback"]
                phase_progress_callback("distill", 0, 3)
                phase_progress_callback("distill", 3, 3)
                phase_progress_callback("persist", 0, 3)
                phase_progress_callback("persist", 3, 3)
                return 3

            self.vault = SimpleNamespace(distill=distill)
            self._collection = object()

    castle = DistillCastle(None, None)
    args = SimpleNamespace(
        wing="w", room="r", dry_run=False, apply=True, config=None, palace=None, backend=None
    )

    with patch("swampcastle.castle.Castle", lambda s, f: castle):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_distill(args)

    out = capsys.readouterr().out
    assert "Distilling" in out
    assert "3/3" in out
    assert "Persisting" in out


def test_cmd_kg_extract_defaults_to_preview_mode(capsys):
    class ProposalCastle(DummyCastle):
        def __init__(self, settings, factory):
            self.calls = []
            self.catalog = SimpleNamespace(status=lambda: None)
            self.search = SimpleNamespace(search=lambda q: None)
            self.vault = SimpleNamespace(distill=lambda **kwargs: 0, reforge=lambda **kwargs: 0)
            self.kg_proposals = SimpleNamespace(
                extract_from_drawers=lambda **kwargs: (
                    self.calls.append(kwargs)
                    or [
                        SimpleNamespace(
                            candidate_id="cand_1",
                            subject_text="swampcastle",
                            predicate="uses",
                            object_text="LanceDB",
                            confidence=0.9,
                            modality="asserted",
                            status="proposed",
                        )
                    ]
                )
            )
            self._collection = object()

    castle = ProposalCastle(None, None)
    args = SimpleNamespace(
        wing="w", room="r", dry_run=False, apply=False, limit=10, palace=None, backend=None
    )

    with patch("swampcastle.castle.Castle", lambda s, f: castle):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_kg_extract(args)

    assert castle.calls == [{"wing": "w", "room": "r", "dry_run": True, "limit": 10}]
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "--apply" in out


def test_cmd_kg_extract_apply_persists_proposals(capsys):
    class ProposalCastle(DummyCastle):
        def __init__(self, settings, factory):
            self.calls = []
            self.catalog = SimpleNamespace(status=lambda: None)
            self.search = SimpleNamespace(search=lambda q: None)
            self.vault = SimpleNamespace(distill=lambda **kwargs: 0, reforge=lambda **kwargs: 0)
            self.kg_proposals = SimpleNamespace(
                extract_from_drawers=lambda **kwargs: (
                    self.calls.append(kwargs)
                    or [
                        SimpleNamespace(
                            candidate_id="cand_1",
                            subject_text="swampcastle",
                            predicate="uses",
                            object_text="LanceDB",
                            confidence=0.9,
                            modality="asserted",
                            status="proposed",
                        )
                    ]
                )
            )
            self._collection = object()

    castle = ProposalCastle(None, None)
    args = SimpleNamespace(
        wing="w", room="r", dry_run=False, apply=True, limit=10, palace=None, backend=None
    )

    with patch("swampcastle.castle.Castle", lambda s, f: castle):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_kg_extract(args)

    assert castle.calls == [{"wing": "w", "room": "r", "dry_run": False, "limit": 10}]
    assert "Extracted 1 candidate triples" in capsys.readouterr().out


def test_cmd_kg_review_lists_candidates(capsys):
    class ProposalCastle(DummyCastle):
        def __init__(self, settings, factory):
            self.catalog = SimpleNamespace(status=lambda: None)
            self.search = SimpleNamespace(search=lambda q: None)
            self.vault = SimpleNamespace(distill=lambda **kwargs: 0, reforge=lambda **kwargs: 0)
            self.kg_proposals = SimpleNamespace(
                list_proposals=lambda filter_params=None: [
                    SimpleNamespace(
                        candidate_id="cand_1",
                        subject_text="SwampCastle",
                        predicate="uses",
                        object_text="LanceDB",
                        confidence=0.9,
                        status="proposed",
                        conflicts_with=[],
                    )
                ]
            )
            self._collection = object()

    args = SimpleNamespace(
        status="proposed",
        predicate=None,
        min_confidence=None,
        wing=None,
        room=None,
        limit=50,
        offset=0,
        conflicts_only=False,
        palace=None,
        backend=None,
    )

    with patch("swampcastle.castle.Castle", lambda s, f: ProposalCastle(s, f)):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_kg_review(args)

    out = capsys.readouterr().out
    assert "cand_1" in out
    assert "SwampCastle" in out
    assert "uses" in out


def test_cmd_kg_review_prints_conflict_marker(capsys):
    class ProposalCastle(DummyCastle):
        def __init__(self, settings, factory):
            self.catalog = SimpleNamespace(status=lambda: None)
            self.search = SimpleNamespace(search=lambda q: None)
            self.vault = SimpleNamespace(distill=lambda **kwargs: 0, reforge=lambda **kwargs: 0)
            self.kg_proposals = SimpleNamespace(
                list_proposals=lambda filter_params=None: [
                    SimpleNamespace(
                        candidate_id="cand_1",
                        subject_text="SwampCastle",
                        predicate="uses",
                        object_text="Clerk",
                        confidence=0.9,
                        status="proposed",
                        conflicts_with=["Auth0"],
                    )
                ]
            )
            self._collection = object()

    args = SimpleNamespace(
        status="proposed",
        predicate=None,
        min_confidence=None,
        wing=None,
        room=None,
        limit=50,
        offset=0,
        conflicts_only=False,
        palace=None,
        backend=None,
    )

    with patch("swampcastle.castle.Castle", lambda s, f: ProposalCastle(s, f)):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_kg_review(args)

    out = capsys.readouterr().out
    assert "CONFLICT" in out
    assert "Auth0" in out


def test_cmd_kg_review_conflicts_only_filters_out_clean_candidates(capsys):
    class ProposalCastle(DummyCastle):
        def __init__(self, settings, factory):
            self.catalog = SimpleNamespace(status=lambda: None)
            self.search = SimpleNamespace(search=lambda q: None)
            self.vault = SimpleNamespace(distill=lambda **kwargs: 0, reforge=lambda **kwargs: 0)
            self.kg_proposals = SimpleNamespace(
                list_proposals=lambda filter_params=None: [
                    SimpleNamespace(
                        candidate_id="cand_conflict",
                        subject_text="SwampCastle",
                        predicate="uses",
                        object_text="Clerk",
                        confidence=0.9,
                        status="proposed",
                        conflicts_with=["Auth0"],
                    ),
                    SimpleNamespace(
                        candidate_id="cand_clean",
                        subject_text="SwampCastle",
                        predicate="uses",
                        object_text="LanceDB",
                        confidence=0.9,
                        status="proposed",
                        conflicts_with=[],
                    ),
                ]
            )
            self._collection = object()

    args = SimpleNamespace(
        status="proposed",
        predicate=None,
        min_confidence=None,
        wing=None,
        room=None,
        limit=50,
        offset=0,
        conflicts_only=True,
        palace=None,
        backend=None,
    )

    with patch("swampcastle.castle.Castle", lambda s, f: ProposalCastle(s, f)):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_kg_review(args)

    out = capsys.readouterr().out
    assert "cand_conflict" in out
    assert "cand_clean" not in out


def test_cmd_kg_accept_and_reject(capsys):
    calls = []

    class ProposalCastle(DummyCastle):
        def __init__(self, settings, factory):
            self.catalog = SimpleNamespace(status=lambda: None)
            self.search = SimpleNamespace(search=lambda q: None)
            self.vault = SimpleNamespace(distill=lambda **kwargs: 0, reforge=lambda **kwargs: 0)
            self.kg_proposals = SimpleNamespace(
                accept=lambda cmd: (
                    calls.append(("accept", cmd))
                    or SimpleNamespace(
                        success=True,
                        candidate_id=cmd.candidate_id,
                        status="accepted",
                        triple_id="t1",
                        subject_text=cmd.subject_text or "SwampCastle",
                        predicate=cmd.predicate or "uses",
                        object_text=cmd.object_text or "Clerk",
                        invalidated_count=(
                            1 if cmd.action == "accept_and_invalidate_conflict" else 0
                        ),
                        error=None,
                    )
                ),
                reject=lambda candidate_id: (
                    calls.append(("reject", candidate_id))
                    or SimpleNamespace(
                        success=True,
                        candidate_id=candidate_id,
                        status="rejected",
                        triple_id=None,
                        subject_text=None,
                        predicate=None,
                        object_text=None,
                        invalidated_count=0,
                        error=None,
                    )
                ),
            )
            self._collection = object()

    accept_args = SimpleNamespace(
        candidate_id="cand_1",
        subject="Auth subsystem",
        predicate="migrated_to",
        object="Clerk",
        valid_from=None,
        valid_to=None,
        invalidate_conflicts=True,
        palace=None,
        backend=None,
    )
    reject_args = SimpleNamespace(candidate_id="cand_2", palace=None, backend=None)

    with patch("swampcastle.castle.Castle", lambda s, f: ProposalCastle(s, f)):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_kg_accept(accept_args)
            commands.cmd_kg_reject(reject_args)

    assert calls[0][0] == "accept"
    assert calls[0][1].action == "accept_and_invalidate_conflict"
    assert calls[1] == ("reject", "cand_2")
    out = capsys.readouterr().out
    assert "accepted" in out.lower()
    assert "rejected" in out.lower()
    assert "invalidated 1 conflicting fact" in out.lower()
    assert "Auth subsystem --migrated_to--> Clerk" in out


def test_cmd_wizard_runs_runtime_wizard():
    with patch("swampcastle.wizard.run_wizard") as mock:
        commands.cmd_wizard(SimpleNamespace())
    mock.assert_called_once_with()


def test_cmd_tune_runs_runtime_tuner():
    with patch("swampcastle.wizard.run_tune") as mock:
        commands.cmd_tune(SimpleNamespace())
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

            def reforge(**kwargs):
                self.calls.append(kwargs)
                progress_callback = kwargs["progress_callback"]
                progress_callback(0, 3)
                progress_callback(2, 3)
                progress_callback(3, 3)
                return 3

            self.vault = SimpleNamespace(reforge=reforge)
            self._collection = object()

    castle = ReforgeCastle(None, None)
    args = SimpleNamespace(
        wing="w", room="r", dry_run=False, embedder="onnx", device="cpu", palace=None, backend=None
    )

    with patch("swampcastle.castle.Castle", lambda s, f: castle):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_reforge(args)

    assert castle.calls[0]["wing"] == "w"
    assert castle.calls[0]["room"] == "r"
    assert castle.calls[0]["dry_run"] is False
    assert callable(castle.calls[0]["progress_callback"])
    out = capsys.readouterr().out
    assert "onnx embedder" in out
    assert "Reforging" in out
    assert "3/3" in out


def test_cmd_reforge_dry_run_does_not_render_progress(capsys):
    class ReforgeCastle(DummyCastle):
        def __init__(self, settings, factory):
            self.calls = []
            self.catalog = SimpleNamespace(status=lambda: None)
            self.search = SimpleNamespace(search=lambda q: None)
            self.vault = SimpleNamespace(reforge=lambda **kwargs: self.calls.append(kwargs) or 3)
            self._collection = object()

    castle = ReforgeCastle(None, None)
    args = SimpleNamespace(
        wing="w", room="r", dry_run=True, embedder="onnx", device="cpu", palace=None, backend=None
    )

    with patch("swampcastle.castle.Castle", lambda s, f: castle):
        with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
            commands.cmd_reforge(args)

    assert castle.calls[0]["progress_callback"] is None
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "Reforging" not in out


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
        commands.cmd_armory(SimpleNamespace(verify=False, json=False, palace=None, backend=None))

    out = capsys.readouterr().out
    assert "all-MiniLM-L6-v2" in out
    assert "minilm" in out
    assert "onnx" in out


def test_cmd_armory_verify_prints_report(capsys):
    fake_report = {
        "embedder": {
            "backend": "onnx",
            "model_name": "all-MiniLM-L6-v2",
            "dimension": 384,
        },
        "fingerprint_hash": "fp123",
        "probe_hash": "probe456",
        "probe_count": 8,
    }

    with patch("swampcastle.embeddings.get_embedder", return_value=object()):
        with patch(
            "swampcastle.embeddings.build_embedding_verification_report", return_value=fake_report
        ):
            commands.cmd_armory(SimpleNamespace(verify=True, json=False, palace=None, backend=None))

    out = capsys.readouterr().out
    assert "Embedder verification" in out
    assert "all-MiniLM-L6-v2" in out
    assert "fp123" in out
    assert "probe456" in out


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

    client = SimpleNamespace(sync=lambda engine, **kw: {"push": {"sent": 2}, "pull": {"received": 3}})
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
