"""Tests for the global runtime configuration wizard."""

from __future__ import annotations

import json

from swampcastle.wizard import run_wizard


def test_wizard_edits_existing_lance_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("swampcastle.runtime_config.Path.home", lambda: tmp_path)
    config_dir = tmp_path / ".swampcastle"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "backend": "lance",
                "castle_path": str(config_dir / "castle"),
                "collection_name": "swampcastle_chests",
                "embedder": "onnx",
            }
        )
    )

    responses = iter(["", str(tmp_path / "custom-castle")])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    run_wizard()

    data = json.loads(config_path.read_text())
    assert data["backend"] == "lance"
    assert data["castle_path"] == str(tmp_path / "custom-castle")
    out = capsys.readouterr().out
    assert "SwampCastle Wizard" in out
    assert "Saved runtime config" in out


def test_wizard_can_switch_to_postgres(tmp_path, monkeypatch):
    monkeypatch.setattr("swampcastle.runtime_config.Path.home", lambda: tmp_path)

    responses = iter(["postgres", str(tmp_path / "castle"), "postgresql://localhost/test"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    run_wizard()

    config_path = tmp_path / ".swampcastle" / "config.json"
    data = json.loads(config_path.read_text())
    assert data["backend"] == "postgres"
    assert data["castle_path"] == str(tmp_path / "castle")
    assert data["database_url"] == "postgresql://localhost/test"
