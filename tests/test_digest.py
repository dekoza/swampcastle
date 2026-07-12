"""Tests for the session digest — the capped payload `status` returns (#24)."""

from datetime import datetime, timedelta

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


class TestProjectSection:
    def test_config_wing_merged_with_slug_siblings(self, castle, tmp_path):
        project = tmp_path / "myproj"
        project.mkdir()
        (project / ".swampcastle.yaml").write_text("wing: myproj\n")
        # Path-slug sibling as transcript mining names it
        slug_wing = str(project).lower().replace("/", "_").replace("-", "_")

        _fill(
            castle,
            [
                ("myproj", "design", "2026-06-01T10:00:00", "doc"),
                ("myproj", "design", "2026-06-02T10:00:00", "doc"),
                ("myproj", "testing", "2026-06-03T10:00:00", "doc"),
                (slug_wing, "planning", "2026-07-01T10:00:00", "doc"),
                (slug_wing, "planning", "2026-07-02T10:00:00", "doc"),
                ("unrelated", "ops", "2026-01-01T10:00:00", "doc"),
            ],
        )

        digest = build_digest(castle, project_dir=str(project)).digest

        assert "## Project" in digest
        project_part = digest.split("## Project")[1].split("## Castle")[0]
        # Merged view across config wing + slug sibling
        assert "5 drawers" in project_part
        assert "myproj" in project_part
        assert slug_wing in project_part
        assert "planning" in project_part
        assert "design" in project_part
        assert "unrelated" not in project_part

    def test_room_overflow_capped_at_ten(self, castle, tmp_path):
        project = tmp_path / "roomy"
        project.mkdir()
        (project / ".swampcastle.yaml").write_text("wing: roomy\n")
        rows = []
        # room_00 gets 13 drawers, room_01 12, ... room_12 1
        for r in range(13):
            rows.extend([("roomy", f"room_{r:02d}", "2026-06-01T10:00:00", "doc")] * (13 - r))
        _fill(castle, rows)

        digest = build_digest(castle, project_dir=str(project)).digest
        project_part = digest.split("## Project")[1].split("## Castle")[0]
        rooms_block = project_part.split("Rooms:")[1].split("Recent:")[0]

        assert "room_09" in rooms_block
        assert "room_10" not in rooms_block
        assert "+3 more" in rooms_block
        assert "list_rooms" in rooms_block

    def test_recent_activity_lists_five_newest_drawers_with_gists(self, castle, tmp_path):
        project = tmp_path / "active"
        project.mkdir()
        (project / ".swampcastle.yaml").write_text("wing: active\n")

        rows = [
            ("active", "roomA", f"2026-07-{day:02d}T09:00:00", f"note from day {day}: " + "x" * 200)
            for day in range(1, 8)  # 7 drawers, days 1..7
        ]
        _fill(castle, rows)

        digest = build_digest(castle, project_dir=str(project)).digest
        project_part = digest.split("## Project")[1].split("## Castle")[0]

        # 5 newest (days 3..7) present, oldest two absent
        for day in range(3, 8):
            assert f"2026-07-{day:02d}" in project_part
            assert f"note from day {day}" in project_part
        assert "2026-07-01" not in project_part
        assert "2026-07-02" not in project_part
        # Gist is the first line, truncated
        for line in project_part.splitlines():
            if "note from day" in line:
                assert len(line) <= 120  # date + room + 80-char gist

    def test_last_diary_entry_pointer(self, castle, tmp_path):
        project = tmp_path / "diaryproj"
        project.mkdir()
        (project / ".swampcastle.yaml").write_text("wing: diaryproj\n")
        _fill(castle, [("diaryproj", "planning", "2026-06-01T10:00:00", "doc")])

        castle._collection.upsert(
            documents=["Session notes: shipped the digest.", "Older entry."],
            ids=["diary_1", "diary_2"],
            metadatas=[
                {
                    "wing": "wing_claude",
                    "room": "diary",
                    "filed_at": "2026-07-10T20:00:00",
                    "topic": "digest shipped",
                    "date": "2026-07-10",
                },
                {
                    "wing": "wing_claude",
                    "room": "diary",
                    "filed_at": "2026-05-01T20:00:00",
                    "topic": "old topic",
                    "date": "2026-05-01",
                },
            ],
        )
        castle.catalog._invalidate_view()

        digest = build_digest(castle, project_dir=str(project)).digest

        assert "Last diary entry" in digest
        assert "digest shipped" in digest
        assert "2026-07-10" in digest
        assert "old topic" not in digest

    def test_no_project_section_without_resolution(self, castle, tmp_path):
        _fill(castle, [("somewing", "r", "2026-05-01T10:00:00", "doc")])
        empty_dir = tmp_path / "nothing_here"
        empty_dir.mkdir()

        digest = build_digest(castle, project_dir=str(empty_dir)).digest
        assert "## Project" not in digest


def _months_ago(months: int) -> str:
    return (datetime.now() - timedelta(days=months * 31)).isoformat()


class TestStaleness:
    def test_flags_wings_older_than_threshold(self, castle):
        _fill(
            castle,
            [
                ("dusty", "r", _months_ago(7), "doc"),
                ("fresh", "r", _months_ago(1), "doc"),
                ("undated", "r", None, "doc"),
            ],
        )

        digest = build_digest(castle).digest

        assert "## Stale" in digest
        stale_part = digest.split("## Stale")[1].split("<!--")[0]
        assert "dusty" in stale_part
        assert "fresh" not in stale_part
        # Undated wings can't be called stale
        assert "undated" not in stale_part

    def test_no_stale_section_when_all_fresh(self, castle):
        _fill(castle, [("fresh", "r", _months_ago(1), "doc")])
        assert "## Stale" not in build_digest(castle).digest

    def test_threshold_from_settings(self, tmp_path):
        settings = CastleSettings(
            castle_path=tmp_path / "castle", staleness_months=1, _env_file=None
        )
        with Castle(settings, InMemoryStorageFactory()) as castle:
            _fill(castle, [("two_months_old", "r", _months_ago(2), "doc")])
            digest = build_digest(castle).digest
        assert "## Stale" in digest
        assert "two_months_old" in digest.split("## Stale")[1]

    def test_stale_list_capped_at_ten(self, castle):
        _fill(
            castle,
            [(f"stale_{i:02d}", "r", _months_ago(8), "doc") for i in range(12)],
        )

        stale_part = build_digest(castle).digest.split("## Stale")[1].split("<!--")[0]
        flagged = [line for line in stale_part.splitlines() if line.startswith("- ")]
        assert len(flagged) == 10
        assert "+2 more" in stale_part
