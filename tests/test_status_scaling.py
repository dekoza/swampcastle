"""Scaling tests for swampcastle.mining.miner.status()."""

from __future__ import annotations


from swampcastle.mining import miner
from swampcastle.storage.memory import InMemoryCollectionStore


class _LargeCollection(InMemoryCollectionStore):
    def __init__(self, total: int):
        super().__init__()
        self._total = total
        self.get_calls = []
        for i in range(total):
            wing = "proj" if i % 2 == 0 else "personal"
            room = "auth" if i % 3 == 0 else "billing"
            self._docs[f"id_{i}"] = {
                "document": f"doc {i}",
                "metadata": {"wing": wing, "room": room},
            }

    def get(self, *, ids=None, where=None, limit=None, offset=None, include=None):
        self.get_calls.append({"limit": limit, "offset": offset, "include": include})
        return super().get(ids=ids, where=where, limit=limit, offset=offset, include=include)


def test_status_paginates_and_reports_true_total(monkeypatch, capsys, tmp_path):
    col = _LargeCollection(total=10050)

    class _Factory:
        def open_collection(self, name):
            return col

    monkeypatch.setattr(miner, "factory_from_settings", lambda settings: _Factory())

    miner.status(str(tmp_path / "castle"))
    out = capsys.readouterr().out

    assert "SwampCastle Status — 10050 drawers" in out
    # More than one page required; the old implementation did a single get(limit=10000)
    assert len(col.get_calls) > 1, f"Expected paginated get() calls, got {col.get_calls}"
    assert any(call["offset"] for call in col.get_calls[1:]), col.get_calls
