"""Tests for contributor detection during ingest."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from swampcastle.mining.contributor import detect_contributor


def _fake_git_author(name):
    def _git_last_author(filepath, project_path):
        return name

    return _git_last_author


def test_no_team_returns_none(tmp_path):
    assert detect_contributor(tmp_path / "file.py", tmp_path, team=None) is None
    assert detect_contributor(tmp_path / "file.py", tmp_path, team=[]) is None


def test_exact_match_against_team(tmp_path):
    with patch("swampcastle.mining.contributor._git_last_author", _fake_git_author("dekoza")):
        result = detect_contributor(tmp_path / "file.py", tmp_path, team=["dekoza", "sarah"])
    assert result == "dekoza"


def test_case_insensitive_match(tmp_path):
    with patch("swampcastle.mining.contributor._git_last_author", _fake_git_author("Dekoza")):
        result = detect_contributor(tmp_path / "file.py", tmp_path, team=["dekoza", "sarah"])
    assert result == "dekoza"


def test_partial_match_in_git_author(tmp_path):
    with patch(
        "swampcastle.mining.contributor._git_last_author", _fake_git_author("Dominik Kozaczko")
    ):
        result = detect_contributor(tmp_path / "file.py", tmp_path, team=["dominik", "sarah"])
    assert result == "dominik"


def test_self_identity_fallback(tmp_path):
    registry = SimpleNamespace(
        is_self=lambda name: name == "Dominik Kozaczko",
        self_identity={"name": "Dominik", "nickname": "dekoza"},
    )
    with patch(
        "swampcastle.mining.contributor._git_last_author", _fake_git_author("Dominik Kozaczko")
    ):
        result = detect_contributor(
            tmp_path / "file.py", tmp_path, team=["dekoza", "sarah"], registry=registry
        )
    assert result == "dekoza"


def test_no_git_returns_none(tmp_path):
    with patch("swampcastle.mining.contributor._git_last_author", lambda f, p: None):
        result = detect_contributor(tmp_path / "file.py", tmp_path, team=["dekoza"])
    assert result is None


def test_unknown_author_returns_none(tmp_path):
    with patch(
        "swampcastle.mining.contributor._git_last_author", _fake_git_author("unknown_person")
    ):
        result = detect_contributor(tmp_path / "file.py", tmp_path, team=["dekoza", "sarah"])
    assert result is None
