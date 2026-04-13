"""Tests for project-local config resolution and migration."""

from __future__ import annotations

from swampcastle.project_config import (
    LEGACY_PROJECT_CONFIG_NAME,
    PROJECT_CONFIG_NAME,
    resolve_project_config,
)


def test_resolve_project_config_prefers_hidden_file(tmp_path, capsys):
    project = tmp_path / "project"
    project.mkdir()
    hidden = project / PROJECT_CONFIG_NAME
    legacy = project / LEGACY_PROJECT_CONFIG_NAME
    hidden.write_text("wing: hidden\n")
    legacy.write_text("wing: legacy\n")

    resolved = resolve_project_config(project)

    assert resolved == hidden
    assert hidden.read_text() == "wing: hidden\n"
    assert legacy.exists()
    assert "ignoring the legacy file" in capsys.readouterr().out.lower()


def test_resolve_project_config_migrates_legacy_file(tmp_path, capsys):
    project = tmp_path / "project"
    project.mkdir()
    legacy = project / LEGACY_PROJECT_CONFIG_NAME
    legacy.write_text("wing: legacy\n")

    resolved = resolve_project_config(project)

    hidden = project / PROJECT_CONFIG_NAME
    assert resolved == hidden
    assert hidden.exists()
    assert hidden.read_text() == "wing: legacy\n"
    assert not legacy.exists()
    assert "migrated legacy project config" in capsys.readouterr().out.lower()


def test_resolve_project_config_returns_none_when_missing(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    assert resolve_project_config(project) is None
