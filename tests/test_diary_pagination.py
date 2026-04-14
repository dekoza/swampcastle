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


def test_diary_read_sees_entries_beyond_old_10k_cap(svc):
    """Regression test for the old limit=10000 implementation.

    Old code fetched only the first 10k diary rows. With 10001 entries it would
    silently miss the most recent entry if insertion order matched timestamp.
    """
    base = datetime(2026, 1, 1, 0, 0, 0)
    n = 10001
    for i in range(n):
        now = base + timedelta(seconds=i)
        svc._col.add(
            ids=[f"diary_cap_{i}"],
            documents=[f"cap entry {i}"],
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

    resp = svc.diary_read(DiaryReadQuery(agent_name="test_agent", last_n=1))
    assert len(resp.entries) == 1
    assert resp.entries[0].content == "cap entry 10000"


def test_diary_empty_returns_message(svc):
    q = DiaryReadQuery(agent_name="ghost", last_n=5)
    resp = svc.diary_read(q)
    assert resp.entries == []
    assert "No diary entries yet" in resp.message


def test_diary_read_avoids_offset_pagination_for_large_result_sets(tmp_path):
    """Regression test for the hostile review.

    Offset-based pagination over LanceDB is O(N²): page 1 scans 1000 rows,
    page 2 scans 2000, page 3 scans 3000, etc. diary_read should fetch diary
    rows in one get() call and use a heap in Python instead of issuing many
    increasingly expensive offset queries.

    This test fails against the old offset-based implementation because the
    fake collection raises as soon as diary_read requests offset>0.
    """

    class FakeCollection:
        def __init__(self):
            self.calls = []

        def get(self, *, ids=None, where=None, limit=None, offset=None, include=None):
            self.calls.append({"limit": limit, "offset": offset, "where": where})
            if offset not in (None, 0):
                raise AssertionError(
                    f"diary_read must not use offset pagination, got offset={offset}"
                )

            n = 1001
            base = datetime(2026, 1, 1, 0, 0, 0)
            return {
                "ids": [f"id_{i}" for i in range(n)],
                "documents": [f"entry {i}" for i in range(n)],
                "metadatas": [
                    {
                        "wing": "wing_test_agent",
                        "room": "diary",
                        "filed_at": (base + timedelta(seconds=i)).isoformat(),
                        "date": (base + timedelta(seconds=i)).strftime("%Y-%m-%d"),
                        "topic": "topic",
                        "agent": "test_agent",
                    }
                    for i in range(n)
                ],
            }

    svc = VaultService(FakeCollection(), WalWriter(tmp_path / "wal"))
    resp = svc.diary_read(DiaryReadQuery(agent_name="test_agent", last_n=5))

    assert len(resp.entries) == 5
    assert resp.entries[0].content == "entry 1000"
    assert len(svc._col.calls) == 1, f"Expected one get() call, got {svc._col.calls}"
