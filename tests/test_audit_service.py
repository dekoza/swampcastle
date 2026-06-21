"""Tests for AuditService — read-only audit-overlay access."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from swampcastle.audit.curation import REQUIRED_WING_NOTE_SECTIONS
from swampcastle.audit.origin import write_origin_manifest
from swampcastle.models.audit import (
    AliasCurationData,
    CatalogCardsResponse,
    CurationResponse,
    OriginLookupResponse,
    TunnelCurationData,
)
from swampcastle.models.origin import SourceOrigin
from swampcastle.services.audit import AuditService
from swampcastle.storage.memory import InMemoryCollectionStore


@pytest.fixture
def col():
    return InMemoryCollectionStore()


@pytest.fixture
def castle_path(tmp_path):
    """Create a castle directory with .swampcastle/ overlay."""
    overlay = tmp_path / ".swampcastle"
    overlay.mkdir()
    return str(tmp_path)


@pytest.fixture
def svc(col, castle_path):
    return AuditService(col, castle_path)


def _curation_dir(castle_path: str) -> Path:
    d = Path(castle_path) / ".swampcastle" / "curation"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_alias_curation(castle_path: str, aliases: dict | None = None):
    """Write an alias curation YAML file."""
    d = _curation_dir(castle_path)
    data = {
        "personas": {},
        "people": {},
        "projects": {},
        "wing_hints": {},
    }
    if aliases:
        for section, entries in aliases.items():
            data[section] = entries
    (d / "aliases.yaml").write_text(yaml.dump(data))


def _write_tunnel_curation(castle_path: str, tunnels: dict | None = None):
    """Write a tunnel curation YAML file."""
    d = _curation_dir(castle_path)
    data = {"allow": [], "deny": [], "boost": []}
    if tunnels:
        for section, entries in tunnels.items():
            data[section] = entries
    (d / "tunnels.yaml").write_text(yaml.dump(data))


def _write_wing_note(castle_path: str, wing: str, sections: dict):
    """Write a wing note markdown file."""
    d = _curation_dir(castle_path) / "wings"
    d.mkdir(parents=True, exist_ok=True)
    lines = []
    for section, entries in sections.items():
        lines.append(f"## {section}")
        for entry in entries:
            lines.append(f"- {entry}")
        lines.append("")
    (d / f"{wing}.md").write_text("\n".join(lines))


def _make_origin(source_file: str, origin_id: str) -> SourceOrigin:
    return SourceOrigin(
        origin_id=origin_id,
        source_kind="project_file",
        source_file=source_file,
        updated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


# ── get_origin ─────────────────────────────────────────────────────────


class TestGetOrigin:
    def test_by_origin_id_found(self, svc, castle_path):
        origin = _make_origin("/home/user/project/README.md", "origin_test123")
        write_origin_manifest(castle_path, origin)

        result = svc.get_origin(origin_id="origin_test123")

        assert isinstance(result, OriginLookupResponse)
        assert result.found is True
        assert result.resolved_by == "origin_id"
        assert result.origin is not None
        assert result.origin.source_file == "/home/user/project/README.md"

    def test_by_origin_id_not_found(self, svc, castle_path):
        result = svc.get_origin(origin_id="origin_nonexistent")

        assert result.found is False
        assert result.resolved_by == "origin_id"
        assert result.origin is None
        assert result.path is not None

    def test_by_source_file_found(self, svc, col, castle_path):
        origin = _make_origin("/home/user/src/app.py", "origin_src456")
        write_origin_manifest(castle_path, origin)

        col.upsert(
            documents=["content"],
            ids=["drawer1"],
            metadatas=[{"source_file": "/home/user/src/app.py", "origin_id": "origin_src456"}],
        )

        result = svc.get_origin(source_file="/home/user/src/app.py")

        assert result.found is True
        assert result.resolved_by == "source_file"
        assert result.origin is not None

    def test_by_source_file_no_drawer_metadata(self, svc, col):
        result = svc.get_origin(source_file="/home/user/nonexistent.py")

        assert result.found is False
        assert result.resolved_by == "source_file"
        assert "No stored drawer metadata" in result.error

    def test_by_source_file_manifest_missing(self, svc, col, castle_path):
        col.upsert(
            documents=["content"],
            ids=["drawer1"],
            metadatas=[
                {"source_file": "/home/user/src/app.py", "origin_id": "origin_missing"}
            ],
        )

        result = svc.get_origin(source_file="/home/user/src/app.py")

        assert result.found is False
        assert result.resolved_by == "source_file"
        assert "missing" in result.error


# ── get_curation ────────────────────────────────────────────────────────


class TestGetCuration:
    def test_empty_curation(self, svc, castle_path):
        _write_alias_curation(castle_path)
        _write_tunnel_curation(castle_path)

        result = svc.get_curation()

        assert isinstance(result, CurationResponse)
        assert result.aliases == AliasCurationData()
        assert result.tunnels == TunnelCurationData()
        assert result.available_wing_notes == []
        assert result.wing_note is None

    def test_with_aliases(self, svc, castle_path):
        _write_alias_curation(
            castle_path,
            aliases={
                "people": {"dekoza": {"canonical": "Dietrich"}},
                "projects": {"indyq": {"canonical": "Indyq"}},
                "wing_hints": {"indyq": "crowdfunding platform"},
            },
        )
        _write_tunnel_curation(castle_path)

        result = svc.get_curation()

        assert result.aliases.people["dekoza"].canonical == "Dietrich"
        assert result.aliases.projects["indyq"].canonical == "Indyq"
        assert result.aliases.wing_hints["indyq"] == "crowdfunding platform"

    def test_with_tunnels(self, svc, castle_path):
        _write_alias_curation(castle_path)
        _write_tunnel_curation(
            castle_path,
            tunnels={
                "allow": [{"wing_a": "proj", "wing_b": "personal", "room": "shared", "weight": 0}],
                "deny": [{"wing_a": "code", "wing_b": "diary", "room": "private", "weight": 0}],
                "boost": [{"wing_a": "proj", "wing_b": "team", "room": "planning", "weight": 5.0}],
            },
        )

        result = svc.get_curation()

        assert len(result.tunnels.allow) == 1
        assert result.tunnels.allow[0].room == "shared"
        assert len(result.tunnels.deny) == 1
        assert len(result.tunnels.boost) == 1
        assert result.tunnels.boost[0].weight == 5.0

    def test_with_wing_note(self, svc, castle_path):
        _write_alias_curation(castle_path)
        _write_tunnel_curation(castle_path)
        _write_wing_note(
            castle_path,
            "proj",
            sections={
                "Pinned context": ["Uses LanceDB", "Postgres planned"],
                "Open threads": ["Migration path unclear"],
                "Stale assumptions": ["ChromaDB is still supported"],
            },
        )

        result = svc.get_curation(wing="proj")

        assert result.wing_note is not None
        assert result.wing_note.wing == "proj"
        assert "Pinned context" in result.wing_note.sections
        assert result.available_wing_notes == ["proj"]

    def test_wing_note_not_found(self, svc, castle_path):
        _write_alias_curation(castle_path)
        _write_tunnel_curation(castle_path)

        result = svc.get_curation(wing="nonexistent")

        assert result.wing_note is None
        assert result.available_wing_notes == []


# ── list_catalog_cards ──────────────────────────────────────────────────


class TestListCatalogCards:
    def test_no_cards(self, svc, castle_path):
        result = svc.list_catalog_cards(wing="proj")

        assert isinstance(result, CatalogCardsResponse)
        assert result.wing == "proj"
        assert result.cards == []
        assert result.path is not None
        assert "proj" in result.path

    def test_with_cards(self, svc, castle_path):
        derived = Path(castle_path) / ".swampcastle" / "derived" / "catalog"
        derived.mkdir(parents=True, exist_ok=True)
        cards_file = derived / "proj.jsonl"
        cards = [
            {
                "wing": "proj",
                "room": "auth",
                "topic": "Auth flow",
                "entities": ["OAuth2", "Clerk"],
                "drawer_ids": ["d1", "d2"],
                "source_files": ["src/auth.py"],
            },
            {
                "wing": "proj",
                "room": "billing",
                "topic": "Billing",
                "entities": ["PayU"],
                "drawer_ids": ["d3"],
                "source_files": ["src/billing.py"],
            },
        ]
        cards_file.write_text("\n".join(json.dumps(c) for c in cards))

        result = svc.list_catalog_cards(wing="proj")

        assert len(result.cards) == 2
        assert result.cards[0].topic == "Auth flow"
        assert result.cards[1].topic == "Billing"
        assert result.cards[0].room == "auth"
