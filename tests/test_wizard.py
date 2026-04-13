"""Tests for the global runtime configuration wizard."""

from __future__ import annotations

import json

from swampcastle.wizard import run_wizard


def test_wizard_backend_only_skips_identity(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("swampcastle.runtime_config.Path.home", lambda: tmp_path)

    responses = iter(["", str(tmp_path / "castle"), "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    run_wizard()

    config_path = tmp_path / ".swampcastle" / "config.json"
    data = json.loads(config_path.read_text())
    assert data["backend"] == "lance"
    out = capsys.readouterr().out
    assert "Wizard complete" in out
    assert "Identity saved" not in out


def test_wizard_edits_existing_lance_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("swampcastle.runtime_config.Path.home", lambda: tmp_path)
    config_dir = tmp_path / ".swampcastle"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps({"backend": "lance", "castle_path": str(config_dir / "castle")})
    )

    responses = iter(["", str(tmp_path / "custom-castle"), "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    run_wizard()

    data = json.loads((config_dir / "config.json").read_text())
    assert data["castle_path"] == str(tmp_path / "custom-castle")
    assert "Saved runtime config" in capsys.readouterr().out


def test_wizard_can_switch_to_postgres(tmp_path, monkeypatch):
    monkeypatch.setattr("swampcastle.runtime_config.Path.home", lambda: tmp_path)

    responses = iter(
        [
            "postgres",
            str(tmp_path / "castle"),
            "postgresql://localhost/test",
            "n",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    run_wizard()

    data = json.loads((tmp_path / ".swampcastle" / "config.json").read_text())
    assert data["backend"] == "postgres"
    assert data["database_url"] == "postgresql://localhost/test"


def test_wizard_with_personal_identity_and_self(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("swampcastle.runtime_config.Path.home", lambda: tmp_path)

    responses = iter(
        [
            "",  # backend default
            str(tmp_path / "castle"),  # castle path
            "y",  # set up identity? yes
            "Riley",  # self name
            "ril",  # self nickname
            "likes dogs",  # self facts
            "2",  # mode: personal
            "Devon, friend",  # person
            "",  # done people
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    run_wizard()

    out = capsys.readouterr().out
    assert "Identity saved" in out

    registry_path = tmp_path / ".swampcastle" / "entity_registry.json"
    registry = json.loads(registry_path.read_text())
    assert registry["self"]["name"] == "Riley"
    assert registry["self"]["nickname"] == "ril"
    assert "likes dogs" in registry["self"]["facts"]
    assert "Devon" in registry["people"]


def test_wizard_with_work_identity_includes_projects(tmp_path, monkeypatch):
    monkeypatch.setattr("swampcastle.runtime_config.Path.home", lambda: tmp_path)

    responses = iter(
        [
            "",  # backend default
            str(tmp_path / "castle"),  # castle path
            "y",  # set up identity? yes
            "Dominik",  # self name
            "dekoza",  # self nickname
            "",  # self facts (blank)
            "1",  # mode: work
            "Sarah, team lead",  # person
            "",  # done people
            "SwampCastle",  # project
            "",  # done projects
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    run_wizard()

    registry_path = tmp_path / ".swampcastle" / "entity_registry.json"
    registry = json.loads(registry_path.read_text())
    assert registry["self"]["name"] == "Dominik"
    assert registry["self"]["nickname"] == "dekoza"
    assert "Sarah" in registry["people"]
    assert "SwampCastle" in registry["projects"]
