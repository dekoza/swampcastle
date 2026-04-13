"""Tests for CatalogService."""

import pytest

from swampcastle.services.catalog import CatalogService
from swampcastle.storage.memory import InMemoryCollectionStore


@pytest.fixture
def col():
    return InMemoryCollectionStore()


@pytest.fixture
def svc(col):
    return CatalogService(col, castle_path="/tmp/test")


class TestStatus:
    def test_empty(self, svc):
        s = svc.status()
        assert s.total_drawers == 0
        assert s.wings == {}
        assert s.rooms == {}

    def test_populated(self, col, svc):
        col.upsert(
            documents=["d1", "d2", "d3"],
            ids=["1", "2", "3"],
            metadatas=[
                {"wing": "proj", "room": "auth"},
                {"wing": "proj", "room": "billing"},
                {"wing": "personal", "room": "journal"},
            ],
        )
        s = svc.status()
        assert s.total_drawers == 3
        assert s.wings == {"proj": 2, "personal": 1}
        assert s.rooms == {"auth": 1, "billing": 1, "journal": 1}
        assert s.castle_path == "/tmp/test"
        assert "SwampCastle" in s.protocol


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
