"""Tests for global runtime config bootstrap."""

from __future__ import annotations

import json

from swampcastle.runtime_config import ensure_runtime_config, runtime_config_path


def test_ensure_runtime_config_creates_default_lance_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("swampcastle.runtime_config.Path.home", lambda: tmp_path)

    config_path = ensure_runtime_config()

    assert config_path == tmp_path / ".swampcastle" / "config.json"
    data = json.loads(config_path.read_text())
    assert data["backend"] == "lance"
    assert data["castle_path"].endswith(".swampcastle/castle")
    out = capsys.readouterr().out
    assert "default runtime config" in out.lower()
    assert "swampcastle wizard" in out


def test_ensure_runtime_config_keeps_existing_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("swampcastle.runtime_config.Path.home", lambda: tmp_path)
    config_path = runtime_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"backend": "postgres", "database_url": "postgres://x"}))

    returned = ensure_runtime_config()

    assert returned == config_path
    data = json.loads(config_path.read_text())
    assert data["backend"] == "postgres"
    assert capsys.readouterr().out == ""


def test_ensure_runtime_config_prints_legacy_guidance(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("swampcastle.runtime_config.Path.home", lambda: tmp_path)
    legacy_palace = tmp_path / ".mempalace" / "palace"
    legacy_palace.mkdir(parents=True)
    (legacy_palace / "chroma.sqlite3").write_text("legacy")

    ensure_runtime_config()

    out = capsys.readouterr().out.lower()
    assert "legacy mempalace" in out
    assert "swampcastle migrate" in out
    assert "swampcastle wizard" in out
