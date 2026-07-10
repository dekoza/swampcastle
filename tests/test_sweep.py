"""Tests for the transcript sweep orchestrator and its systemd units."""

import json

import pytest

from swampcastle.mining import sweep as sweep_mod
from swampcastle.mining.sweep import (
    SERVICE_UNIT,
    TIMER_UNIT,
    install_timer,
    sweep_transcripts,
)


@pytest.fixture
def roots(tmp_path):
    """Two transcript roots with project subdirs, one missing root."""
    claude = tmp_path / "claude-projects"
    pi = tmp_path / "pi-sessions"
    for root, names in ((claude, ["proj-a", "proj-b"]), (pi, ["--home-x--"])):
        for name in names:
            d = root / name
            d.mkdir(parents=True)
            f = d / "session.jsonl"
            f.write_text(json.dumps({"type": "session", "version": "3"}) + "\n")
    missing = tmp_path / "does-not-exist"
    return [("claude-code", claude), ("pi", pi), ("gone", missing)]


def test_sweep_iterates_project_subdirs(roots, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(sweep_mod, "mine_convos", lambda d, p, **kw: calls.append((str(d), str(p))))
    result = sweep_transcripts(str(tmp_path / "palace"), roots=roots)
    swept_dirs = sorted(c[0] for c in calls)
    assert len(swept_dirs) == 3
    assert any(d.endswith("--home-x--") for d in swept_dirs)
    assert any(d.endswith("proj-a") for d in swept_dirs)
    assert all(c[1].endswith("palace") for c in calls)
    assert result["projects_swept"] == 3
    assert result["projects_failed"] == []


def test_sweep_skips_missing_root(roots, tmp_path, monkeypatch):
    monkeypatch.setattr(sweep_mod, "mine_convos", lambda d, p, **kw: None)
    result = sweep_transcripts(str(tmp_path / "palace"), roots=roots)
    assert result["roots_missing"] == ["gone"]


def test_sweep_continues_after_project_error(roots, tmp_path, monkeypatch):
    def boom(d, p, **kw):
        if "proj-a" in str(d):
            raise RuntimeError("broken project")

    monkeypatch.setattr(sweep_mod, "mine_convos", boom)
    result = sweep_transcripts(str(tmp_path / "palace"), roots=roots)
    assert result["projects_swept"] == 2
    assert len(result["projects_failed"]) == 1
    assert "proj-a" in result["projects_failed"][0]


def test_sweep_reports_oversize(roots, tmp_path, monkeypatch):
    monkeypatch.setattr(sweep_mod, "mine_convos", lambda d, p, **kw: None)
    monkeypatch.setattr("swampcastle.mining.convo.MAX_FILE_SIZE", 100)
    big = roots[1][1] / "--home-x--" / "big.jsonl"
    big.write_text("x" * 200)
    result = sweep_transcripts(str(tmp_path / "palace"), roots=roots)
    assert len(result["oversize"]) == 1
    assert result["oversize"][0].endswith("big.jsonl")


def test_sweep_dry_run_passes_through(roots, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(sweep_mod, "mine_convos", lambda d, p, **kw: seen.append(kw.get("dry_run")))
    sweep_transcripts(str(tmp_path / "palace"), roots=roots, dry_run=True)
    assert seen and all(seen)


def test_service_unit_shape():
    assert "Type=oneshot" in SERVICE_UNIT
    assert "ExecStart=%h/.local/bin/swampcastle sweep" in SERVICE_UNIT


def test_timer_unit_shape():
    assert "OnUnitActiveSec=6h" in TIMER_UNIT
    assert "Persistent=true" in TIMER_UNIT
    assert "WantedBy=timers.target" in TIMER_UNIT


def test_install_timer_writes_units(tmp_path):
    written = install_timer(unit_dir=tmp_path, run_systemctl=False)
    service = tmp_path / "swampcastle-sweep.service"
    timer = tmp_path / "swampcastle-sweep.timer"
    assert service.read_text() == SERVICE_UNIT
    assert timer.read_text() == TIMER_UNIT
    assert sorted(str(p) for p in written) == sorted([str(service), str(timer)])
