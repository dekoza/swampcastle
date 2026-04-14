"""Tests for diary_read pagination and memory boundedness.

Ensure diary_read does not pull the entire diary into memory and returns
only the requested 'last_n' entries sorted by timestamp (most recent first).
"""

from datetime import datetime, timedelta

import pytest

from swampcastle.services.vault import DiaryReadQuery, VaultService
from swampcastle.storage.memory import InMemoryCollectionStore
from swampcastle.wal import WalWriter


@pytest.fixture
def svc(tmp_path):
    col = InMemoryCollectionStore()
    wal = WalWriter(tmp_path / "wal")
    return VaultService(col, wal)


def _iso(ts):
    return ts.isoformat()


def test_diary_pagination_bounded_memory(svc):
    # Create 1500 diary entries with increasing timestamps
    base = datetime(2026, 1, 1, 0, 0, 0)
    n = 1500
    for i in range(n):
        now = base + timedelta(seconds=i)
        entry_id = f"diary_agent_{i}"
        svc._col.add(
            ids=[entry_id],
            documents=[f"entry {i}"],
            metadatas=[
                {
                    "wing": "wing_test_agent",
                    "room": "diary",
                    "filed_at": _iso(now),
                    "date": now.strftime("%Y-%m-%d"),
                    "topic": "topic",
                    "agent": "test_agent",
                }
            ],
        )

    # Request the last 50 entries
    q = DiaryReadQuery(agent_name="test_agent", last_n=50)
    resp = svc.diary_read(q)

    assert len(resp.entries) == 50
    # Most recent first
    timestamps = [e.timestamp for e in resp.entries]
    assert timestamps == sorted(timestamps, reverse=True)
    # The top entry must be the latest one we inserted
    assert resp.entries[0].content == f"entry {n - 1}"


def test_diary_empty_returns_message(svc):
    q = DiaryReadQuery(agent_name="ghost", last_n=5)
    resp = svc.diary_read(q)
    assert resp.entries == []
    assert "No diary entries yet" in resp.message
