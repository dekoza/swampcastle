"""Tests for CatalogService."""

import re

import pytest

from swampcastle.services.catalog import CatalogService
from swampcastle.storage.memory import InMemoryCollectionStore


@pytest.fixture
def col():
    return InMemoryCollectionStore()


@pytest.fixture
def svc(col):
    return CatalogService(col, castle_path="/tmp/test")


class TestCatalogScanConsolidation:
    def test_list_wings_list_rooms_taxonomy_activity_share_single_scan(self, col, svc):
        """list_wings(), list_rooms(), get_taxonomy(), wing_activity() must share one scan."""
        col.upsert(
            documents=["a", "b", "c"],
            ids=["1", "2", "3"],
            metadatas=[
                {"wing": "proj", "room": "auth"},
                {"wing": "proj", "room": "billing"},
                {"wing": "personal", "room": "diary"},
            ],
        )

        original_get = col.get
        get_call_count = 0
        def counting_get(**kwargs):
            nonlocal get_call_count
            get_call_count += 1
            return original_get(**kwargs)
        col.get = counting_get

        wings = svc.list_wings()
        assert wings.wings == {"proj": 2, "personal": 1}

        rooms = svc.list_rooms()
        assert rooms.rooms == {"auth": 1, "billing": 1, "diary": 1}

        tax = svc.get_taxonomy()
        assert tax.taxonomy["proj"]["auth"] == 1
        assert tax.taxonomy["personal"]["diary"] == 1

        activity = svc.wing_activity()
        assert set(activity) == {"proj", "personal"}

        # All 4 calls should share a single _scan_all pass
        assert get_call_count == 1, f"Expected 1 shared scan, got {get_call_count}"

    def test_brief_does_own_scan(self, col, svc):
        """brief() needs its own wing-scoped scan for contributors + source_files."""
        col.upsert(
            documents=["a", "b"],
            ids=["1", "2"],
            metadatas=[
                {"wing": "proj", "room": "auth", "contributor": "dekoza", "source_file": "a.py"},
                {"wing": "other", "room": "ops", "contributor": "sarah", "source_file": "b.py"},
            ],
        )

        original_get = col.get
        get_call_count = 0
        def counting_get(**kwargs):
            nonlocal get_call_count
            get_call_count += 1
            return original_get(**kwargs)
        col.get = counting_get

        svc.list_wings()  # triggers initial scan
        calls_after_status = get_call_count

        brief = svc.brief("proj")
        assert brief.total_drawers == 1
        assert brief.contributors == {"dekoza": 1}
        # brief() does its own wing-scoped scan
        assert get_call_count > calls_after_status

    def test_new_drawer_invalidates_catalog_cache(self, col, svc):
        """Adding a drawer must invalidate the cached catalog view."""
        col.upsert(
            documents=["a"],
            ids=["1"],
            metadatas=[{"wing": "proj", "room": "auth"}],
        )

        assert svc.list_wings().wings == {"proj": 1}

        # Simulate what VaultService does: mutate collection + invalidate cache
        col.upsert(
            documents=["b"],
            ids=["2"],
            metadatas=[{"wing": "personal", "room": "diary"}],
        )
        svc._invalidate_view()

        assert svc.list_wings().wings == {"proj": 1, "personal": 1}


class TestWingActivity:
    def test_tracks_newest_timestamp_per_wing(self, col, svc):
        col.upsert(
            documents=["d1", "d2", "d3"],
            ids=["1", "2", "3"],
            metadatas=[
                {"wing": "proj", "room": "auth", "created_at": "2026-01-01T10:00:00"},
                {"wing": "proj", "room": "billing", "filed_at": "2026-03-01T10:00:00"},
                {"wing": "personal", "room": "journal"},
            ],
        )
        activity = svc.wing_activity()
        assert activity["proj"] == "2026-03-01T10:00:00"
        assert activity["personal"] is None


class TestCastleProtocolText:
    """The full protocol text lives on as a constant until it migrates into
    the MCP server instructions field."""

    def test_protocol_is_compact_and_operational(self, svc):
        from swampcastle.services.catalog import CASTLE_PROTOCOL as protocol
        assert "Never state project history, past decisions, people, or prior work" in protocol
        assert "swampcastle_search" in protocol
        assert "swampcastle_kg_query" in protocol
        assert "do not guess." in protocol
        assert "swampcastle_check_duplicate" in protocol
        assert "swampcastle_kg_invalidate" in protocol
        assert "ON WAKE-UP" not in protocol
        assert "This protocol ensures" not in protocol

    def test_protocol_documents_every_canonical_tool(self, svc):
        """Every registered MCP tool must appear in the herald protocol."""
        from swampcastle.mcp.tools import CANONICAL_TOOL_NAMES
        from swampcastle.services.catalog import CASTLE_PROTOCOL as protocol

        found = set(re.findall(r"swampcastle_(\w+)", protocol))
        missing = set(CANONICAL_TOOL_NAMES) - found
        assert not missing, f"Missing from CASTLE_PROTOCOL: {sorted(missing)}"


class TestListWings:
    def test_empty(self, svc):
        r = svc.list_wings()
        assert r.wings == {}

    def test_counts(self, col, svc):
        col.upsert(
            documents=["a", "b", "c"],
            ids=["1", "2", "3"],
            metadatas=[{"wing": "a"}, {"wing": "a"}, {"wing": "b"}],
        )
        r = svc.list_wings()
        assert r.wings == {"a": 2, "b": 1}


class TestListRooms:
    def test_all(self, col, svc):
        col.upsert(
            documents=["a", "b"],
            ids=["1", "2"],
            metadatas=[{"wing": "w", "room": "r1"}, {"wing": "w", "room": "r2"}],
        )
        r = svc.list_rooms()
        assert r.rooms == {"r1": 1, "r2": 1}
        assert r.wing == "all"

    def test_filtered(self, col, svc):
        col.upsert(
            documents=["a", "b", "c"],
            ids=["1", "2", "3"],
            metadatas=[
                {"wing": "w1", "room": "shared"},
                {"wing": "w2", "room": "shared"},
                {"wing": "w1", "room": "private"},
            ],
        )
        r = svc.list_rooms(wing="w1")
        assert r.wing == "w1"
        assert r.rooms == {"shared": 1, "private": 1}


class TestTaxonomy:
    def test_tree(self, col, svc):
        col.upsert(
            documents=["a", "b", "c"],
            ids=["1", "2", "3"],
            metadatas=[
                {"wing": "proj", "room": "auth"},
                {"wing": "proj", "room": "auth"},
                {"wing": "personal", "room": "diary"},
            ],
        )
        r = svc.get_taxonomy()
        assert r.taxonomy["proj"]["auth"] == 2
        assert r.taxonomy["personal"]["diary"] == 1


class TestWingBrief:
    def test_brief_counts_rooms_contributors_and_files(self, col, svc):
        col.upsert(
            documents=["a", "b", "c", "d"],
            ids=["1", "2", "3", "4"],
            metadatas=[
                {
                    "wing": "proj",
                    "room": "auth",
                    "contributor": "dekoza",
                    "source_file": "src/auth.py",
                },
                {
                    "wing": "proj",
                    "room": "auth",
                    "contributor": "dekoza",
                    "source_file": "src/auth.py",
                },
                {
                    "wing": "proj",
                    "room": "billing",
                    "contributor": "sarah",
                    "source_file": "src/billing.py",
                },
                {"wing": "other", "room": "ops", "source_file": "ops.txt"},
            ],
        )

        r = svc.brief("proj")

        assert r.wing == "proj"
        assert r.total_drawers == 3
        assert r.rooms == {"auth": 2, "billing": 1}
        assert r.contributors == {"dekoza": 2, "sarah": 1}
        assert r.source_files == 2

    def test_brief_returns_empty_summary_for_unknown_wing(self, svc):
        r = svc.brief("missing")
        assert r.wing == "missing"
        assert r.total_drawers == 0
        assert r.rooms == {}
        assert r.contributors == {}
        assert r.source_files == 0


class TestAaakSpec:
    def test_returns_string(self, svc):
        spec = svc.get_aaak_spec()
        assert "AAAK" in spec
