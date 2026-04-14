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
        assert "delete_drawer" in ops


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
