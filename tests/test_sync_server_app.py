"""Tests for sync_server.create_app without requiring FastAPI extra."""

from __future__ import annotations

import asyncio
import gzip
import json
import sys
import types
from types import SimpleNamespace

import pytest

from swampcastle.sync import ChangeSet, MergeResult, SyncRecord


class FakeFastAPI:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.routes = {"GET": {}, "POST": {}}

    def get(self, path):
        def decorator(func):
            self.routes["GET"][path] = func
            return func

        return decorator

    def post(self, path):
        def decorator(func):
            self.routes["POST"][path] = func
            return func

        return decorator


class FakeRequest:
    def __init__(self, payload=None, headers=None, raw_body=None):
        self._payload = payload
        self.headers = headers or {}
        self._raw_body = raw_body

    async def json(self):
        return self._payload

    async def body(self):
        if self._raw_body is not None:
            return self._raw_body
        return json.dumps(self._payload).encode("utf-8")


def _response_payload(response):
    if hasattr(response, "body"):
        return json.loads(response.body.decode("utf-8"))
    return response


def _install_fake_fastapi(monkeypatch):
    module = types.ModuleType("fastapi")
    module.FastAPI = FakeFastAPI
    module.Request = FakeRequest
    module.HTTPException = Exception  # minimal stub; auth tests use the real FastAPI
    monkeypatch.setitem(sys.modules, "fastapi", module)


def test_create_app_raises_helpful_import_error(monkeypatch):
    monkeypatch.delitem(sys.modules, "fastapi", raising=False)
    import swampcastle.sync_server as server

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "fastapi":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(ImportError, match=r"swampcastle\[server\]"):
        server.create_app()


def test_create_app_registers_routes_and_lifespan(monkeypatch):
    _install_fake_fastapi(monkeypatch)
    import swampcastle.sync_server as server

    app = server.create_app()

    assert isinstance(app, FakeFastAPI)
    assert app.kwargs["lifespan"] is server._lifespan
    assert "/health" in app.routes["GET"]
    assert "/sync/status" in app.routes["GET"]
    assert "/sync/push" in app.routes["POST"]
    assert "/sync/pull" in app.routes["POST"]


def test_create_app_routes_use_engine(monkeypatch):
    _install_fake_fastapi(monkeypatch)
    import swampcastle.sync_server as server

    remote_changes = ChangeSet(
        source_node="remote",
        records=[
            SyncRecord(
                id="r1",
                document="doc",
                metadata={
                    "wing": "proj",
                    "room": "auth",
                    "source_file": "",
                    "node_id": "remote",
                    "seq": 1,
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
            )
        ],
    )
    engine = SimpleNamespace(
        _col=SimpleNamespace(count=lambda: 4),
        _identity=SimpleNamespace(node_id="node-1"),
        version_vector={"node-1": 2},
        apply_changes=lambda cs: MergeResult(
            accepted=len(cs.records), rejected_conflicts=0, errors=[]
        ),
        get_changes_since=lambda vv: remote_changes,
    )
    monkeypatch.setattr(server, "_get_engine", lambda: engine)
    monkeypatch.setattr(server, "_get_sync_api_key", lambda: None)

    app = server.create_app()

    assert app.routes["GET"]["/health"]() == {"status": "ok", "service": "swampcastle-sync"}
    fake_req = FakeRequest({})
    assert _response_payload(app.routes["GET"]["/sync/status"](fake_req)) == {
        "node_id": "node-1",
        "version_vector": {"node-1": 2},
        "total_drawers": 4,
        "capabilities": {"gzip_request_bodies": True},
    }

    push_req = FakeRequest(
        {
            "source_node": "client",
            "records": [
                {
                    "id": "x1",
                    "document": "doc",
                    "metadata": {
                        "wing": "proj",
                        "room": "a",
                        "source_file": "",
                        "node_id": "client",
                        "seq": 1,
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    },
                }
            ],
        }
    )
    pull_req = FakeRequest({"version_vector": {}})

    push_resp = _response_payload(asyncio.run(app.routes["POST"]["/sync/push"](push_req)))
    pull_resp = _response_payload(asyncio.run(app.routes["POST"]["/sync/pull"](pull_req)))

    assert push_resp == {"accepted": 1, "rejected_conflicts": 0, "errors": []}
    assert pull_resp["source_node"] == "remote"
    assert pull_resp["records"][0]["id"] == "r1"


def test_read_json_body_decodes_gzip(monkeypatch):
    _install_fake_fastapi(monkeypatch)
    import swampcastle.sync_server as server

    payload = {"source_node": "client", "records": []}
    request = FakeRequest(
        headers={"Content-Encoding": "gzip"},
        raw_body=gzip.compress(json.dumps(payload).encode("utf-8")),
    )

    decoded = asyncio.run(server._read_json_body(request))

    assert decoded == payload


def test_make_json_response_gzips_large_payload():
    pytest.importorskip("fastapi")
    import swampcastle.sync_server as server

    payload = {"records": [{"document": "x" * 10_000, "metadata": {}}]}

    response = server._make_json_response(payload, accept_encoding="gzip")

    assert response.headers["Content-Encoding"] == "gzip"
    assert json.loads(gzip.decompress(response.body).decode("utf-8")) == payload


def test_lifespan_shutdowns_engine(monkeypatch):
    _install_fake_fastapi(monkeypatch)
    import swampcastle.sync_server as server

    called = []
    monkeypatch.setattr(server, "_shutdown_engine", lambda: called.append(True))

    async def run_lifespan():
        async with server._lifespan(None):
            pass

    asyncio.run(run_lifespan())
    assert called == [True]
