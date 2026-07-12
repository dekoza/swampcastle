"""Tests for the session digest — the capped payload `status` returns (#24)."""

import pytest

from swampcastle.castle import Castle
from swampcastle.services.digest import DIGEST_MAX_BYTES, DIGEST_MAX_LINES, build_digest
from swampcastle.settings import CastleSettings
from swampcastle.storage.memory import InMemoryStorageFactory


@pytest.fixture
def castle(tmp_path):
    settings = CastleSettings(castle_path=tmp_path / "castle", _env_file=None)
    with Castle(settings, InMemoryStorageFactory()) as c:
        yield c


def _fill(castle, rows):
    """Upsert (wing, room, created_at, doc) rows straight into the collection."""
    castle._collection.upsert(
        documents=[doc for *_, doc in rows],
        ids=[f"id_{i}" for i in range(len(rows))],
        metadatas=[
            {"wing": wing, "room": room, **({"created_at": ts} if ts else {})}
            for wing, room, ts, _ in rows
        ],
    )
    castle.catalog._invalidate_view()


class TestProtocolGist:
    def test_empty_castle_digest_carries_gist_and_extension_point(self, castle):
        result = build_digest(castle)

        digest = result.digest
        # Read-first discipline stated up front
        assert "query first" in digest.lower()
        # Zoom tools named client-agnostically
        for tool in ("search", "get_taxonomy", "get_aaak_spec", "list_wings"):
            assert tool in digest
        # The stale hardcoded prefix must be gone
        assert "swampcastle_" not in digest
        # Marked extension point for milestone D's core-memory blocks
        assert "<!-- extension point: core-memory blocks" in digest

        assert result.partial is False
        assert len(digest.splitlines()) <= DIGEST_MAX_LINES
        assert len(digest.encode("utf-8")) <= DIGEST_MAX_BYTES


class TestGlobalGist:
    def test_totals_top_wings_and_overflow(self, castle):
        rows = []
        # 17 wings: wing_00 has 18 drawers, wing_01 has 17, ... wing_16 has 2
        for w in range(17):
            for d in range(18 - w):
                rows.append((f"wing_{w:02d}", "roomx", f"2026-0{(w % 6) + 1}-15T12:00:00", "doc"))
        _fill(castle, rows)
        castle.graph.kg_add("SwampCastle", "uses", "LanceDB")

        digest = build_digest(castle).digest

        assert f"{len(rows)} drawers" in digest
        # KG counts from the graph store (subject + object = 2 entities)
        assert "2 entities" in digest
        assert "1 facts" in digest
        # Top-15 wings by drawer count, each with its last-activity date
        assert "wing_00" in digest and "18" in digest
        assert "wing_14" in digest
        # 16th and 17th wings fall behind the overflow line
        assert "wing_15" not in digest
        assert "wing_16" not in digest
        assert "+2 more" in digest
        assert "list_wings" in digest
        # last-activity date rendered for a top wing (wing_00 → month 01)
        assert "2026-01-15" in digest

    def test_no_overflow_line_when_wings_fit(self, castle):
        _fill(castle, [("only_wing", "r", "2026-05-01T10:00:00", "doc")])
        digest = build_digest(castle).digest
        assert "only_wing" in digest
        assert "+0 more" not in digest
