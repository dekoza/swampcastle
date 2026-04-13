"""Tests for swampcastle.sync_client."""

from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from swampcastle.sync import ChangeSet, MergeResult, SyncRecord
from swampcastle.sync_client import SyncClient


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def test_request_builds_json_body_and_parses_response(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["body"] = req.data.decode("utf-8")
        captured["timeout"] = timeout
        return _FakeResponse({"ok": True})

    monkeypatch.setattr("swampcastle.sync_client.urlopen", fake_urlopen)

    client = SyncClient("http://server:7433", timeout=9.0)
    result = client._request("POST", "/sync/push", {"x": 1})

    assert result == {"ok": True}
    assert captured == {
        "url": "http://server:7433/sync/push",
        "method": "POST",
        "body": '{"x": 1}',
        "timeout": 9.0,
    }


def test_is_reachable_returns_true_for_ok_status(monkeypatch):
    monkeypatch.setattr(SyncClient, "_request", lambda self, method, path: {"status": "ok"})
    assert SyncClient("http://server").is_reachable() is True


def test_is_reachable_returns_false_on_error(monkeypatch):
    def fail(self, method, path):
        raise URLError("down")

    monkeypatch.setattr(SyncClient, "_request", fail)
    assert SyncClient("http://server").is_reachable() is False


def test_get_status_push_and_pull_delegate_to_request(monkeypatch):
    calls = []

    def fake_request(self, method, path, body=None):
        calls.append((method, path, body))
        if path == "/sync/status":
            return {"node_id": "server", "version_vector": {}, "total_drawers": 0}
        if path == "/sync/push":
            return {"accepted": 1, "rejected_conflicts": 0}
        if path == "/sync/pull":
            return {"source_node": "server", "records": []}
        raise AssertionError(path)

    monkeypatch.setattr(SyncClient, "_request", fake_request)
    client = SyncClient("http://server")
    changeset = ChangeSet(
        source_node="local",
        records=[
            SyncRecord(
                id="d1",
                document="doc",
                metadata={
                    "wing": "proj",
                    "room": "auth",
                    "source_file": "",
                    "node_id": "local",
                    "seq": 1,
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
            )
        ],
    )

    assert client.get_status()["node_id"] == "server"
    assert client.push(changeset)["accepted"] == 1
    pulled = client.pull({"local": 1})
    assert isinstance(pulled, ChangeSet)
    assert calls == [
        ("GET", "/sync/status", None),
        ("POST", "/sync/push", changeset.to_dict()),
        ("POST", "/sync/pull", {"version_vector": {"local": 1}}),
    ]


def test_sync_returns_summary_without_push_or_pull(monkeypatch):
    client = SyncClient("http://server")
    monkeypatch.setattr(
        client,
        "get_status",
        lambda: {"node_id": "server", "version_vector": {}, "total_drawers": 0},
    )
    monkeypatch.setattr(client, "push", lambda changeset: pytest.fail("push should not be called"))
    monkeypatch.setattr(client, "pull", lambda vv: ChangeSet(source_node="server", records=[]))

    engine = SimpleNamespace(
        get_changes_since=lambda vv: ChangeSet(source_node="local", records=[]),
        version_vector={"local": 1},
    )

    result = client.sync(engine)

    assert result == {
        "server": "server",
        "push": {"sent": 0, "accepted": 0, "rejected": 0},
        "pull": {"received": 0, "accepted": 0, "rejected": 0},
        "local_vv": {"local": 1},
    }


def test_sync_pushes_and_pulls_changes(monkeypatch):
    client = SyncClient("http://server")
    monkeypatch.setattr(
        client,
        "get_status",
        lambda: {"node_id": "server", "version_vector": {"server": 2}, "total_drawers": 3},
    )

    outgoing = ChangeSet(
        source_node="local",
        records=[
            SyncRecord(
                id="d1",
                document="local doc",
                metadata={
                    "wing": "proj",
                    "room": "auth",
                    "source_file": "",
                    "node_id": "local",
                    "seq": 1,
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
            )
        ],
    )
    incoming = ChangeSet(
        source_node="server",
        records=[
            SyncRecord(
                id="d2",
                document="remote doc",
                metadata={
                    "wing": "proj",
                    "room": "billing",
                    "source_file": "",
                    "node_id": "server",
                    "seq": 3,
                    "updated_at": "2026-01-02T00:00:00+00:00",
                },
            )
        ],
    )

    monkeypatch.setattr(client, "push", lambda changeset: {"accepted": 1, "rejected_conflicts": 0})
    monkeypatch.setattr(client, "pull", lambda vv: incoming)

    engine = SimpleNamespace(
        get_changes_since=lambda vv: outgoing,
        version_vector={"local": 1, "server": 2},
        apply_changes=lambda changeset: MergeResult(accepted=1, rejected_conflicts=0, errors=[]),
    )

    result = client.sync(engine)

    assert result["server"] == "server"
    assert result["push"] == {"sent": 1, "accepted": 1, "rejected": 0}
    assert result["pull"] == {"received": 1, "accepted": 1, "rejected": 0}
