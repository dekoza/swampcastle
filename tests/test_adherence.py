"""Tests for adherence instrumentation — per-session MCP protocol metrics."""

import json
from pathlib import Path

import pytest

from swampcastle.audit.adherence import (
    AdherenceRecorder,
    derive_metrics,
    load_sessions,
    sessions_dir_for_castle,
)


def _record_with_calls(*tools: str) -> dict:
    return {
        "session_id": "s1",
        "started_at": "2026-07-12T10:00:00Z",
        "ended_at": None,
        "client_name": "claude-code",
        "client_version": "2.1.0",
        "project_dir": "/home/u/proj",
        "calls": [{"tool": t, "at": f"2026-07-12T10:00:{i:02d}Z"} for i, t in enumerate(tools)],
        "counts": {},
    }


@pytest.fixture
def castle_path(tmp_path):
    (tmp_path / ".swampcastle").mkdir()
    return str(tmp_path)


@pytest.fixture
def recorder(castle_path):
    return AdherenceRecorder.for_castle(castle_path)


def _session_files(castle_path: str) -> list[Path]:
    sessions_dir = Path(castle_path) / ".swampcastle" / "adherence" / "sessions"
    return sorted(sessions_dir.glob("*.json"))


class TestRecorder:
    def test_session_started_persists_record_with_client_info(self, recorder, castle_path):
        recorder.session_started({"name": "claude-code", "version": "2.1.0"})

        files = _session_files(castle_path)
        assert len(files) == 1
        record = json.loads(files[0].read_text())
        assert record["client_name"] == "claude-code"
        assert record["client_version"] == "2.1.0"
        assert record["started_at"]
        assert record["ended_at"] is None
        assert record["calls"] == []

    def test_record_call_persists_sequence_counts_and_project_dir(self, recorder, castle_path):
        recorder.session_started({"name": "pi"})
        recorder.record_call("status", {"project_dir": "/home/u/proj"})
        recorder.record_call("search", {"query": "foo"})
        recorder.record_call("search", {"query": "bar"})

        record = json.loads(_session_files(castle_path)[0].read_text())
        assert [c["tool"] for c in record["calls"]] == ["status", "search", "search"]
        assert all(c["at"] for c in record["calls"])
        assert record["counts"] == {"status": 1, "search": 2}
        assert record["project_dir"] == "/home/u/proj"

    def test_session_ended_stamps_ended_at(self, recorder, castle_path):
        recorder.session_started(None)
        recorder.session_ended()

        record = json.loads(_session_files(castle_path)[0].read_text())
        assert record["ended_at"] is not None

    def test_recorder_never_raises_on_unwritable_dir(self, tmp_path):
        blocked = tmp_path / "blocked"
        blocked.write_text("a file, not a directory")
        recorder = AdherenceRecorder(blocked / "sessions")

        recorder.session_started({"name": "claude-code"})
        recorder.record_call("status", {})
        recorder.session_ended()


class TestDeriveMetrics:
    def test_adherent_session(self):
        metrics = derive_metrics(_record_with_calls("status", "search", "add_drawer", "checkpoint"))
        assert metrics["total_calls"] == 4
        assert metrics["status_called"] is True
        assert metrics["search_called"] is True
        assert metrics["read_before_write"] is True
        assert metrics["checkpoint_at_end"] is True
        assert metrics["last_tool"] == "checkpoint"

    def test_write_without_prior_read_flags_ordering(self):
        metrics = derive_metrics(_record_with_calls("add_drawer", "search"))
        assert metrics["read_before_write"] is False
        assert metrics["checkpoint_at_end"] is False

    def test_read_only_session_has_null_write_metrics(self):
        metrics = derive_metrics(_record_with_calls("status", "search"))
        assert metrics["read_before_write"] is None
        assert metrics["checkpoint_at_end"] is None

    def test_session_with_no_calls(self):
        metrics = derive_metrics(_record_with_calls())
        assert metrics["total_calls"] == 0
        assert metrics["status_called"] is False
        assert metrics["last_tool"] is None

    def test_diary_write_counts_as_session_filing(self):
        metrics = derive_metrics(_record_with_calls("search", "add_drawer", "diary_write"))
        assert metrics["checkpoint_at_end"] is True


class TestLoadSessions:
    def _write_session(self, castle_path, session_id, started_at):
        record = _record_with_calls("status")
        record["session_id"] = session_id
        record["started_at"] = started_at
        sessions_dir = sessions_dir_for_castle(castle_path)
        sessions_dir.mkdir(parents=True, exist_ok=True)
        (sessions_dir / f"{session_id}.json").write_text(json.dumps(record))

    def test_returns_most_recent_first_with_limit(self, castle_path):
        self._write_session(castle_path, "a", "2026-07-10T10:00:00Z")
        self._write_session(castle_path, "b", "2026-07-12T10:00:00Z")
        self._write_session(castle_path, "c", "2026-07-11T10:00:00Z")

        sessions = load_sessions(castle_path, limit=2)
        assert [s["session_id"] for s in sessions] == ["b", "c"]

    def test_empty_castle_returns_empty_list(self, castle_path):
        assert load_sessions(castle_path) == []

    def test_corrupt_file_is_skipped(self, castle_path):
        self._write_session(castle_path, "good", "2026-07-12T10:00:00Z")
        sessions_dir = sessions_dir_for_castle(castle_path)
        (sessions_dir / "bad.json").write_text("{not json")

        sessions = load_sessions(castle_path)
        assert [s["session_id"] for s in sessions] == ["good"]


class TestAuditServiceSurface:
    def test_adherence_sessions_returns_records_with_metrics(self, castle_path):
        from swampcastle.services.audit import AuditService
        from swampcastle.storage.memory import InMemoryCollectionStore

        recorder = AdherenceRecorder.for_castle(castle_path)
        recorder.session_started({"name": "claude-code", "version": "2.1.0"})
        recorder.record_call("status", {"project_dir": "/x"})
        recorder.record_call("checkpoint", {})

        svc = AuditService(InMemoryCollectionStore(), castle_path)
        sessions = svc.adherence_sessions(limit=5)
        assert len(sessions) == 1
        assert sessions[0]["client_name"] == "claude-code"
        assert sessions[0]["metrics"]["status_called"] is True
        assert sessions[0]["metrics"]["checkpoint_at_end"] is True


class TestCliAdherence:
    def _args(self, castle_path, **overrides):
        from types import SimpleNamespace

        defaults = {"palace": castle_path, "backend": None, "limit": 10, "json": False}
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _seed_session(self, castle_path):
        recorder = AdherenceRecorder.for_castle(castle_path)
        recorder.session_started({"name": "claude-code", "version": "2.1.0"})
        recorder.record_call("status", {"project_dir": "/home/u/proj"})
        recorder.record_call("checkpoint", {})
        recorder.session_ended()

    def test_prints_session_metrics(self, castle_path, capsys):
        from swampcastle.cli.commands.query import cmd_adherence

        self._seed_session(castle_path)
        cmd_adherence(self._args(castle_path))

        out = capsys.readouterr().out
        assert "claude-code" in out
        assert "/home/u/proj" in out
        assert "status_called" in out

    def test_json_output_is_parseable(self, castle_path, capsys):
        from swampcastle.cli.commands.query import cmd_adherence

        self._seed_session(castle_path)
        cmd_adherence(self._args(castle_path, json=True))

        payload = json.loads(capsys.readouterr().out)
        assert len(payload) == 1
        assert payload[0]["metrics"]["checkpoint_at_end"] is True

    def test_empty_castle_prints_no_sessions(self, castle_path, capsys):
        from swampcastle.cli.commands.query import cmd_adherence

        cmd_adherence(self._args(castle_path))
        assert "No adherence sessions recorded" in capsys.readouterr().out

    def test_dispatches_from_argv(self, capsys, monkeypatch, tmp_path):
        from unittest.mock import patch as mock_patch

        from swampcastle.cli.main import main

        monkeypatch.setattr("swampcastle.runtime_config.Path.home", lambda: tmp_path)
        monkeypatch.delenv("SWAMPCASTLE_CASTLE_PATH", raising=False)
        with mock_patch("sys.argv", ["swampcastle", "adherence", "--limit", "5"]):
            main()
        assert "Adherence" in capsys.readouterr().out


class TestServerInstrumentation:
    def test_handler_records_session_and_tool_calls(self, tmp_path):
        from swampcastle.castle import Castle
        from swampcastle.mcp.server import create_handler
        from swampcastle.settings import CastleSettings
        from swampcastle.storage.memory import InMemoryStorageFactory

        settings = CastleSettings(castle_path=tmp_path / "castle", _env_file=None)
        with Castle(settings, InMemoryStorageFactory()) as castle:
            handler = create_handler(castle)
            assert handler.recorder is not None

            handler(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "clientInfo": {"name": "claude-code", "version": "2.1.0"},
                    },
                }
            )
            handler(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "status", "arguments": {"project_dir": "/x"}},
                }
            )
            handler(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "swampcastle_search", "arguments": {"query": "foo"}},
                }
            )

        sessions = load_sessions(str(settings.castle_path))
        assert len(sessions) == 1
        record = sessions[0]
        assert record["client_name"] == "claude-code"
        assert record["project_dir"] == "/x"
        # Legacy alias resolves to the canonical name before recording.
        assert record["counts"] == {"status": 1, "search": 1}
