"""Tests for swampcastle.sync_client."""

from __future__ import annotations

import gzip
import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from swampcastle.sync import ChangeSet, MergeResult, SyncRecord
from swampcastle.sync_client import SyncClient


class _FakeResponse:
    def __init__(self, payload: dict | None = None, *, raw: bytes | None = None, headers=None):
        self._payload = payload
        self._raw = raw
        self.headers = headers or {}

    def read(self):
        if self._raw is not None:
            return self._raw
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
        captured["auth"] = req.headers.get("Authorization")
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
        "auth": None,
    }


def test_request_adds_bearer_header_when_api_key_passed(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["auth"] = req.headers.get("Authorization")
        return _FakeResponse({"ok": True})

    monkeypatch.setattr("swampcastle.sync_client.urlopen", fake_urlopen)

    client = SyncClient("http://server:7433", api_key="secret-token")
    client._request("POST", "/sync/push", {"x": 1})

    assert captured["auth"] == "Bearer secret-token"


def test_request_decodes_gzip_responses(monkeypatch):
    payload = {"ok": True, "records": [1, 2, 3]}

    def fake_urlopen(req, timeout):
        return _FakeResponse(
            raw=gzip.compress(json.dumps(payload).encode("utf-8")),
            headers={"Content-Encoding": "gzip"},
        )

    monkeypatch.setattr("swampcastle.sync_client.urlopen", fake_urlopen)

    client = SyncClient("http://server:7433")

    assert client._request("POST", "/sync/pull", {"version_vector": {}}) == payload


def test_request_leaves_large_json_bodies_plain_without_server_capability(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["encoding"] = req.headers.get("Content-encoding")
        captured["body"] = req.data
        return _FakeResponse({"ok": True})

    monkeypatch.setattr("swampcastle.sync_client.urlopen", fake_urlopen)

    client = SyncClient("http://server:7433")
    client._request("POST", "/sync/push", {"records": [{"document": "x" * 10_000}]})

    assert captured["encoding"] is None
    assert json.loads(captured["body"].decode("utf-8")) == {
        "records": [{"document": "x" * 10_000}]
    }


def test_request_gzips_large_json_bodies(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["encoding"] = req.headers.get("Content-encoding")
        captured["body"] = req.data
        return _FakeResponse({"ok": True})

    monkeypatch.setattr("swampcastle.sync_client.urlopen", fake_urlopen)

    client = SyncClient("http://server:7433")
    client._server_supports_gzip_requests = True
    client._request("POST", "/sync/push", {"records": [{"document": "x" * 10_000}]})

    assert captured["encoding"] == "gzip"
    assert json.loads(gzip.decompress(captured["body"]).decode("utf-8")) == {
        "records": [{"document": "x" * 10_000}]
    }


def test_request_reads_api_key_from_env(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["auth"] = req.headers.get("Authorization")
        return _FakeResponse({"ok": True})

    monkeypatch.setenv("SWAMPCASTLE_SYNC_API_KEY", "env-token")
    monkeypatch.setattr("swampcastle.sync_client.urlopen", fake_urlopen)

    client = SyncClient("http://server:7433")
    client._request("POST", "/sync/push", {"x": 1})

    assert captured["auth"] == "Bearer env-token"


def test_is_reachable_returns_true_for_ok_status(monkeypatch):
    monkeypatch.setattr(SyncClient, "_request", lambda self, method, path: {"status": "ok"})
    assert SyncClient("http://server").is_reachable() is True


def test_is_reachable_returns_false_on_error(monkeypatch):
    def fail(self, method, path):
        raise URLError("down")

    monkeypatch.setattr(SyncClient, "_request", fail)
    assert SyncClient("http://server").is_reachable() is False


def test_get_status_propagates_http_401(monkeypatch):
    def fake_urlopen(req, timeout):
        raise HTTPError(req.full_url, 401, "Unauthorized", hdrs=None, fp=None)

    monkeypatch.setattr("swampcastle.sync_client.urlopen", fake_urlopen)
    client = SyncClient("http://server", api_key="wrong-token")

    with pytest.raises(HTTPError) as exc:
        client.get_status()

    assert exc.value.code == 401


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


def test_get_status_records_gzip_request_capability(monkeypatch):
    monkeypatch.setattr(
        SyncClient,
        "_request",
        lambda self, method, path, body=None: {
            "node_id": "server",
            "version_vector": {},
            "total_drawers": 0,
            "capabilities": {"gzip_request_bodies": True},
        },
    )

    client = SyncClient("http://server")

    status = client.get_status()

    assert status["node_id"] == "server"
    assert client._server_supports_gzip_requests is True


def test_pull_paged_single_page(monkeypatch):
    """pull_paged returns a single ChangeSet when has_more is False."""
    pages = [
        {"source_node": "server", "records": [{"id": "r1", "document": "d", "metadata": {}}], "has_more": False},
    ]
    calls = []

    def fake_request(self, method, path, body=None):
        calls.append(body)
        return pages[len(calls) - 1]

    monkeypatch.setattr(SyncClient, "_request", fake_request)
    client = SyncClient("http://server")
    cs = client.pull_paged({"local": 1})

    assert isinstance(cs, ChangeSet)
    assert len(cs.records) == 1
    assert cs.records[0].id == "r1"
    assert len(calls) == 1
    assert calls[0] == {"version_vector": {"local": 1}, "limit": 500, "offset": 0}


def test_pull_paged_multiple_pages(monkeypatch):
    """pull_paged loops until has_more is False and concatenates all records."""
    page1_records = [{"id": f"r{i}", "document": "d", "metadata": {}} for i in range(3)]
    page2_records = [{"id": f"r{i}", "document": "d", "metadata": {}} for i in range(3, 5)]
    responses = [
        {"source_node": "server", "records": page1_records, "has_more": True},
        {"source_node": "server", "records": page2_records, "has_more": False},
    ]
    calls = []

    def fake_request(self, method, path, body=None):
        calls.append(body)
        return responses[len(calls) - 1]

    monkeypatch.setattr(SyncClient, "_request", fake_request)
    client = SyncClient("http://server")
    cs = client.pull_paged({"local": 1}, page_size=3)

    assert len(cs.records) == 5
    assert {r.id for r in cs.records} == {f"r{i}" for i in range(5)}
    assert len(calls) == 2
    assert calls[0]["offset"] == 0
    assert calls[1]["offset"] == 3


def test_pull_paged_uses_same_vv_for_all_pages(monkeypatch):
    """All page requests must use the same version_vector, not an updated one."""
    calls = []
    responses = [
        {"source_node": "s", "records": [{"id": "r0", "document": "d", "metadata": {"node_id": "s", "seq": 1}}], "has_more": True},
        {"source_node": "s", "records": [], "has_more": False},
    ]

    def fake_request(self, method, path, body=None):
        calls.append(body)
        return responses[len(calls) - 1]

    monkeypatch.setattr(SyncClient, "_request", fake_request)
    client = SyncClient("http://server")
    client.pull_paged({"local": 5}, page_size=1)

    assert calls[0]["version_vector"] == {"local": 5}
    assert calls[1]["version_vector"] == {"local": 5}



    client = SyncClient("http://server")
    monkeypatch.setattr(
        client,
        "get_status",
        lambda: {"node_id": "server", "version_vector": {}, "total_drawers": 0, "protocol_version": "2024-11-05"},
    )
    monkeypatch.setattr(client, "push", lambda changeset: pytest.fail("push should not be called"))
    monkeypatch.setattr(client, "pull_paged", lambda vv, **kw: ChangeSet(source_node="server", records=[]))

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


def test_pull_paged_calls_progress_callback(monkeypatch):
    """progress_callback receives (received_so_far, total) after each page."""
    page1 = [{"id": f"r{i}", "document": "d", "metadata": {}} for i in range(3)]
    page2 = [{"id": f"r{i}", "document": "d", "metadata": {}} for i in range(3, 5)]
    responses = [
        {"source_node": "s", "records": page1, "has_more": True, "total": 5},
        {"source_node": "s", "records": page2, "has_more": False, "total": None},
    ]
    calls = []

    def fake_request(self, method, path, body=None):
        calls.append(body)
        return responses[len(calls) - 1]

    monkeypatch.setattr(SyncClient, "_request", fake_request)
    client = SyncClient("http://server")
    progress = []
    cs = client.pull_paged(
        {"local": 1},
        page_size=3,
        progress_callback=lambda received, total: progress.append((received, total)),
    )

    assert len(cs.records) == 5
    assert progress == [(3, 5), (5, 5)]


def test_pull_paged_skips_callback_when_server_has_no_total(monkeypatch):
    """Callback is not invoked when the server omits total (old-server compat)."""
    response = {
        "source_node": "s",
        "records": [{"id": "r0", "document": "d", "metadata": {}}],
        "has_more": False,
    }

    monkeypatch.setattr(SyncClient, "_request", lambda self, *a, **kw: response)
    client = SyncClient("http://server")
    progress = []
    cs = client.pull_paged({}, progress_callback=lambda r, t: progress.append((r, t)))

    assert len(cs.records) == 1
    assert progress == []  # no total → callback silent


def test_sync_pushes_and_pulls_changes(monkeypatch):
    client = SyncClient("http://server")
    monkeypatch.setattr(
        client,
        "get_status",
        lambda: {"node_id": "server", "version_vector": {"server": 2}, "total_drawers": 3, "protocol_version": "2024-11-05"}
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
    monkeypatch.setattr(client, "pull_paged", lambda vv, **kw: incoming)

    engine = SimpleNamespace(
        get_changes_since=lambda vv: outgoing,
        version_vector={"local": 1, "server": 2},
        apply_changes=lambda changeset: MergeResult(accepted=1, rejected_conflicts=0, errors=[]),
    )

    result = client.sync(engine)

    assert result["server"] == "server"
    assert result["push"] == {"sent": 1, "accepted": 1, "rejected": 0}
    assert result["pull"] == {"received": 1, "accepted": 1, "rejected": 0}
