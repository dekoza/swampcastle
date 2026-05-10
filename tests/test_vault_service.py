"""Tests for VaultService."""

import pytest

from swampcastle.models.drawer import AddDrawerCommand, DeleteDrawerCommand
from swampcastle.models.diary import DiaryWriteCommand
from swampcastle.services.vault import DiaryReadQuery, VaultService
from swampcastle.storage.memory import InMemoryCollectionStore
from swampcastle.wal import WalWriter


@pytest.fixture
def col():
    return InMemoryCollectionStore()


@pytest.fixture
def wal(tmp_path):
    return WalWriter(tmp_path / "wal")


@pytest.fixture
def svc(col, wal):
    return VaultService(col, wal)


class TestAddDrawer:
    def test_roundtrip(self, svc, col):
        r = svc.add_drawer(
            AddDrawerCommand(
                wing="proj",
                room="arch",
                content="chose postgres",
            )
        )
        assert r.success is True
        assert r.drawer_id is not None
        assert col.count() == 1

    def test_idempotent(self, svc, col):
        cmd = AddDrawerCommand(wing="w", room="r", content="same content")
        svc.add_drawer(cmd)
        r2 = svc.add_drawer(cmd)
        assert r2.success is True
        assert r2.reason == "already_exists"
        assert col.count() == 1

    def test_different_content(self, svc, col):
        svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="aaa"))
        svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="bbb"))
        assert col.count() == 2

    def test_wal_logged(self, svc, wal):
        svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="logged"))
        entries = wal.read_entries()
        assert len(entries) == 1
        assert entries[0]["operation"] == "add_drawer"


class TestDeleteDrawer:
    def test_delete_existing(self, svc, col):
        r = svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="to delete"))
        dr = svc.delete_drawer(DeleteDrawerCommand(drawer_id=r.drawer_id))
        assert dr.success is True
        assert col.count() == 0

    def test_delete_nonexistent(self, svc):
        dr = svc.delete_drawer(DeleteDrawerCommand(drawer_id="nope"))
        assert dr.success is False
        assert "not found" in dr.error.lower()

    def test_wal_logged(self, svc, wal):
        r = svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="x"))
        svc.delete_drawer(DeleteDrawerCommand(drawer_id=r.drawer_id))
        ops = [e["operation"] for e in wal.read_entries()]
        # delete_drawer now creates tombstone + collects immediately
        assert "create_tombstone" in ops
        assert "gc_collect" in ops


def test_get_drawers_forwards_limit_and_offset(wal):
    class SpyCollection:
        def __init__(self):
            self.calls = []

        def get(self, **kwargs):
            self.calls.append(kwargs)
            return {"ids": []}

    collection = SpyCollection()
    svc = VaultService(collection, wal)

    svc.get_drawers(
        where={"wing": "proj"},
        include=["metadatas"],
        limit=25,
        offset=50,
    )

    assert collection.calls == [
        {
            "where": {"wing": "proj"},
            "include": ["metadatas"],
            "limit": 25,
            "offset": 50,
        }
    ]


class TestDiary:
    def test_write_and_read(self, svc):
        svc.diary_write(
            DiaryWriteCommand(
                agent_name="reviewer",
                entry="found bug in auth",
            )
        )
        resp = svc.diary_read(DiaryReadQuery(agent_name="reviewer"))
        assert len(resp.entries) == 1
        assert "found bug" in resp.entries[0].content

    def test_empty_diary(self, svc):
        resp = svc.diary_read(DiaryReadQuery(agent_name="nobody"))
        assert resp.entries == []
        assert resp.message is not None

    def test_diary_write_result(self, svc):
        r = svc.diary_write(
            DiaryWriteCommand(
                agent_name="ops",
                entry="deploy ok",
                topic="deploy",
            )
        )
        assert r.success is True
        assert r.agent == "ops"
        assert r.topic == "deploy"

    def test_diary_respects_last_n(self, svc):
        for i in range(5):
            svc.diary_write(
                DiaryWriteCommand(
                    agent_name="bot",
                    entry=f"entry {i}",
                )
            )
        resp = svc.diary_read(DiaryReadQuery(agent_name="bot", last_n=2))
        assert len(resp.entries) == 2

    def test_diary_wal_logged(self, svc, wal):
        svc.diary_write(
            DiaryWriteCommand(
                agent_name="test",
                entry="wal test",
            )
        )
        ops = [e["operation"] for e in wal.read_entries()]
        assert "diary_write" in ops


# ── Wave 2: tombstone-first deletion ────────────────────────────────────


class TestTombstoneLifecycle:
    def test_create_tombstone_hides_record_from_get(self, svc, col):
        r = svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="secret data"))
        drawer_id = r.drawer_id
        assert svc.get_drawers(ids=[drawer_id])["ids"] == [drawer_id]

        svc.create_tombstone(drawer_id, deleted_by="admin", reason="gdpr")

        # target record hidden from normal reads (via VaultService)
        result = svc.get_drawers(ids=[drawer_id])
        assert result["ids"] == []

        # tombstone record is visible via storage-level raw access
        all_docs = col.get()
        tombstones = [rid for rid in all_docs["ids"] if rid.startswith("tombstone:")]
        assert len(tombstones) == 1

    def test_include_tombstoned_reveals_hidden_records(self, svc, col):
        r = svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="data"))
        drawer_id = r.drawer_id
        svc.create_tombstone(drawer_id, deleted_by="admin", reason="test")

        docs = svc.get_drawers(
            ids=[drawer_id],
            include_tombstoned=True,
        )
        assert docs["ids"] == [drawer_id]

    def test_is_tombstoned(self, svc, col):
        r = svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="x"))
        assert svc.is_tombstoned(r.drawer_id) is False

        svc.create_tombstone(r.drawer_id, deleted_by="admin", reason="test")
        assert svc.is_tombstoned(r.drawer_id) is True

    def test_untombstoned_record_not_hidden(self, svc, col):
        r1 = svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="keep"))
        r2 = svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="delete"))
        assert col.count() == 2

        svc.create_tombstone(r2.drawer_id, deleted_by="admin", reason="test")

        # r1 still visible via VaultService
        docs = svc.get_drawers(ids=[r1.drawer_id])
        assert docs["ids"] == [r1.drawer_id]

        # r2 hidden via VaultService
        docs2 = svc.get_drawers(ids=[r2.drawer_id])
        assert docs2["ids"] == []

    def test_list_pending_gc_empty_when_no_expired_tombstones(self, svc, col):
        from datetime import datetime, timezone

        r = svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="x"))
        svc.create_tombstone(
            r.drawer_id,
            deleted_by="admin",
            reason="test",
            grace_days=90,
        )
        items = svc.list_pending_gc(executed_at=datetime.now(timezone.utc))
        assert items == []

    def test_list_pending_gc_returns_expired_tombstones(self, svc, col):
        from datetime import datetime, timedelta, timezone

        r = svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="x"))
        svc.create_tombstone(
            r.drawer_id,
            deleted_by="admin",
            reason="test",
            grace_days=1,
        )
        future = datetime.now(timezone.utc) + timedelta(days=2)
        items = svc.list_pending_gc(executed_at=future)
        assert len(items) == 1
        assert items[0] == r.drawer_id

    def test_gc_collect_removes_target_and_tombstone(self, svc, col):
        from datetime import datetime, timedelta, timezone

        r = svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="x"))
        drawer_id = r.drawer_id
        svc.create_tombstone(
            drawer_id,
            deleted_by="admin",
            reason="test",
            grace_days=1,
        )
        future = datetime.now(timezone.utc) + timedelta(days=2)

        result = svc.gc_collect([drawer_id], executed_at=future)
        assert result.deleted_ids == [drawer_id]

        # both target and tombstone gone
        all_ids = col.get()["ids"]
        assert drawer_id not in all_ids
        for rid in all_ids:
            assert not rid.startswith("tombstone:")

    def test_gc_collect_ignores_unexpired_tombstones(self, svc, col):
        from datetime import datetime, timezone

        r = svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="x"))
        svc.create_tombstone(
            r.drawer_id,
            deleted_by="admin",
            reason="test",
            grace_days=90,
        )
        now = datetime.now(timezone.utc)
        result = svc.gc_collect([r.drawer_id], executed_at=now)
        assert result.deleted_ids == []

        # target still exists (hidden by tombstone but retrievable with flag)
        docs = svc.get_drawers(
            ids=[r.drawer_id],
            include_tombstoned=True,
        )
        assert docs["ids"] == [r.drawer_id]

    def test_gc_collect_ignores_untombstoned_ids(self, svc, col):
        r = svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="x"))
        from datetime import datetime, timezone

        result = svc.gc_collect(
            [r.drawer_id],
            executed_at=datetime.now(timezone.utc),
        )
        assert result.deleted_ids == []
        # VaultService still returns the record (no tombstone exists)
        docs = svc.get_drawers(ids=[r.drawer_id])
        assert docs["ids"] == [r.drawer_id]

    def test_delete_drawer_still_works_as_immediate_gc(self, svc, col):
        """Backward compat: delete_drawer creates tombstone + gc_collect."""
        r = svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="to delete"))
        dr = svc.delete_drawer(DeleteDrawerCommand(drawer_id=r.drawer_id))
        assert dr.success is True
        # Tombstone + target both gone after immediate gc
        assert col.count() == 0

    def test_delete_drawer_nonexistent_still_fails(self, svc):
        dr = svc.delete_drawer(DeleteDrawerCommand(drawer_id="nope"))
        assert dr.success is False

    def test_tombstone_wal_logged(self, svc, wal):
        r = svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="logged"))
        svc.create_tombstone(r.drawer_id, deleted_by="admin", reason="audit")
        ops = [e["operation"] for e in wal.read_entries()]
        assert "create_tombstone" in ops

    def test_gc_collect_wal_logged(self, svc, wal):
        from datetime import datetime, timedelta, timezone

        r = svc.add_drawer(AddDrawerCommand(wing="w", room="r", content="x"))
        svc.create_tombstone(r.drawer_id, deleted_by="admin", reason="test", grace_days=1)
        future = datetime.now(timezone.utc) + timedelta(days=2)
        svc.gc_collect([r.drawer_id], executed_at=future)
        ops = [e["operation"] for e in wal.read_entries()]
        assert "gc_collect" in ops


# ── Reforge ───────────────────────────────────────────────────────────


class TestReforge:
    def test_reforge_all_drawers(self, svc, col):
        for i in range(5):
            svc.add_drawer(AddDrawerCommand(wing="w", room="r", content=f"doc {i}"))
        assert col.count() == 5

        count = svc.reforge()
        assert count == 5
        assert col.count() == 5

    def test_reforge_filtered_by_wing(self, svc, col):
        svc.add_drawer(AddDrawerCommand(wing="alpha", room="r", content="a"))
        svc.add_drawer(AddDrawerCommand(wing="beta", room="r", content="b"))
        count = svc.reforge(wing="alpha")
        assert count == 1

    def test_reforge_dry_run_returns_count_without_mutating(self, svc, col):
        for i in range(3):
            svc.add_drawer(AddDrawerCommand(wing="w", room="r", content=f"doc {i}"))
        count = svc.reforge(dry_run=True)
        assert count == 3

    def test_reforge_progress_callback(self, svc, col):
        for i in range(5):
            svc.add_drawer(AddDrawerCommand(wing="w", room="r", content=f"doc {i}"))
        progress_calls = []

        def cb(processed, total):
            progress_calls.append((processed, total))

        svc.reforge(batch_size=2, progress_callback=cb)
        # Should receive: (0, 5), (2, 5), (4, 5), (5, 5)
        assert progress_calls[0] == (0, 5)
        assert progress_calls[-1] == (5, 5)
        assert len(progress_calls) >= 2

    def test_reforge_no_drawers(self, svc):
        assert svc.reforge() == 0
