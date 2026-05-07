"""Tests for audit curation files."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from swampcastle.audit.curation import (
    load_alias_curation,
    load_tunnel_curation,
    load_wing_note,
    resolve_wing_hint,
)


def test_load_alias_curation_defaults_when_file_missing(tmp_path):
    aliases = load_alias_curation(tmp_path / "castle")

    assert aliases.personas == {}
    assert aliases.people == {}
    assert aliases.projects == {}
    assert aliases.wing_hints == {}


def test_load_tunnel_curation_parses_allow_deny_and_boost(tmp_path):
    castle_path = tmp_path / "castle"
    curation_dir = castle_path / ".swampcastle" / "curation"
    curation_dir.mkdir(parents=True)
    (curation_dir / "tunnels.yaml").write_text(
        yaml.safe_dump(
            {
                "allow": [
                    {"wing_a": "swampcastle", "wing_b": "cognitive_ai", "room": "embeddings"}
                ],
                "deny": [{"wing_a": "swampcastle", "wing_b": "general", "room": "python"}],
                "boost": [
                    {
                        "wing_a": "swampcastle",
                        "wing_b": "cognitive_ai",
                        "room": "sync",
                        "weight": 0.15,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    tunnels = load_tunnel_curation(castle_path)

    assert len(tunnels.allow) == 1
    assert len(tunnels.deny) == 1
    assert len(tunnels.boost) == 1
    assert tunnels.boost[0].weight == 0.15


def test_load_wing_note_parses_required_sections(tmp_path):
    castle_path = tmp_path / "castle"
    notes_dir = castle_path / ".swampcastle" / "curation" / "wings"
    notes_dir.mkdir(parents=True)
    (notes_dir / "swampcastle.md").write_text(
        "# swampcastle\n\n"
        "## Pinned context\n"
        "- v4 uses Castle + services.\n\n"
        "## Open threads\n"
        "- Add alias overrides.\n\n"
        "## Stale assumptions\n"
        "- Files alone are enough.\n",
        encoding="utf-8",
    )

    note = load_wing_note(castle_path, "swampcastle")

    assert note is not None
    assert note.wing == "swampcastle"
    assert note.sections["Pinned context"] == ["v4 uses Castle + services."]
    assert note.sections["Open threads"] == ["Add alias overrides."]
    assert note.sections["Stale assumptions"] == ["Files alone are enough."]


def test_load_wing_note_rejects_missing_required_sections(tmp_path):
    castle_path = tmp_path / "castle"
    notes_dir = castle_path / ".swampcastle" / "curation" / "wings"
    notes_dir.mkdir(parents=True)
    (notes_dir / "swampcastle.md").write_text(
        "# swampcastle\n\n## Pinned context\n- only one section\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing required sections"):
        load_wing_note(castle_path, "swampcastle")


def test_resolve_wing_hint_matches_source_path(tmp_path):
    castle_path = tmp_path / "castle"
    curation_dir = castle_path / ".swampcastle" / "curation"
    curation_dir.mkdir(parents=True)
    (curation_dir / "aliases.yaml").write_text(
        yaml.safe_dump({"wing_hints": {"claude-session": "swampcastle"}}),
        encoding="utf-8",
    )

    hint = resolve_wing_hint(castle_path, Path("/tmp/exports/claude-session-001.jsonl"))

    assert hint == "swampcastle"
