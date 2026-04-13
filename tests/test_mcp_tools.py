"""Tests for swampcastle.mcp — rebuilt MCP server."""

import io
import json
from types import SimpleNamespace

import pytest

from swampcastle.castle import Castle
from swampcastle.models import AddDrawerCommand, SearchQuery
from swampcastle.settings import CastleSettings
from swampcastle.storage.memory import InMemoryStorageFactory


@pytest.fixture
def castle(tmp_path):
    settings = CastleSettings(castle_path=tmp_path / "castle", _env_file=None)
    with Castle(settings, InMemoryStorageFactory()) as c:
        yield c


@pytest.fixture
def tools(castle):
    from swampcastle.mcp.tools import register_tools
    return register_tools(castle)


class TestToolRegistry:
    def test_19_tools_registered(self, tools):
        assert len(tools) == 19

    def test_all_have_schemas(self, tools):
        for name, tool in tools.items():
            assert "type" in tool.input_schema, f"{name} missing schema"

    def test_all_have_handlers(self, tools):
        for name, tool in tools.items():
            assert callable(tool.handler), f"{name} handler not callable"

    def test_tool_names_prefixed(self, tools):
        for name in tools:
            assert name.startswith("swampcastle_"), f"{name} not prefixed"

    def test_search_schema_from_model(self, tools):
        schema = tools["swampcastle_search"].input_schema
        assert "query" in schema["properties"]
        assert schema["required"] == ["query"]


class TestToolDispatch:
    def test_status_empty(self, tools):
        result = tools["swampcastle_status"].handler()
        assert result.total_drawers == 0

    def test_search_empty(self, tools):
        result = tools["swampcastle_search"].handler(
            SearchQuery(query="anything")
        )
        assert result.results == []

    def test_add_then_search(self, tools):
        add_result = tools["swampcastle_add_drawer"].handler(
            AddDrawerCommand(wing="test", room="arch", content="chose postgres for scale")
        )
        assert add_result.success

        search_result = tools["swampcastle_search"].handler(
            SearchQuery(query="postgres")
        )
        assert len(search_result.results) > 0

    def test_kg_add_then_query(self, tools):
        from swampcastle.models import AddTripleCommand, KGQueryParams
        tools["swampcastle_kg_add"].handler(
            AddTripleCommand(subject="Kai", predicate="works_on", object="Orion")
        )
        result = tools["swampcastle_kg_query"].handler(
            KGQueryParams(entity="Kai")
        )
        assert result.count == 1

    def test_aaak_spec(self, tools):
        result = tools["swampcastle_get_aaak_spec"].handler()
        assert "AAAK" in result


class TestMcpMain:
    def test_main_uses_factory_from_settings(self, monkeypatch, tmp_path):
        from swampcastle.mcp import server

        used = {}

        class DummyCastle:
            def __init__(self, settings, factory):
                used["settings"] = settings
                used["factory"] = factory

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

        factory = object()
        monkeypatch.setattr(server, "Castle", DummyCastle)
        monkeypatch.setattr(server, "create_handler", lambda castle: lambda request: None)
        monkeypatch.setattr("swampcastle.storage.factory_from_settings", lambda settings: factory)
        monkeypatch.setattr("sys.stdin", io.StringIO(""))

        server.main()

        assert used["factory"] is factory
        assert used["settings"].collection_name == "swampcastle_chests"


class TestJsonRpcHandler:
    @pytest.fixture
    def handler(self, castle):
        from swampcastle.mcp.server import create_handler
        return create_handler(castle)

    def test_initialize(self, handler):
        req = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2024-11-05"}}
        resp = handler(req)
        assert resp["result"]["protocolVersion"]
        assert resp["result"]["serverInfo"]["name"] == "swampcastle"

    def test_tools_list(self, handler):
        handler({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2024-11-05"}})
        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        resp = handler(req)
        tool_names = [t["name"] for t in resp["result"]["tools"]]
        assert "swampcastle_search" in tool_names
        assert len(tool_names) == 19

    def test_tool_call(self, handler):
        handler({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2024-11-05"}})
        req = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
               "params": {"name": "swampcastle_status", "arguments": {}}}
        resp = handler(req)
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "total_drawers" in content

    def test_unknown_tool(self, handler):
        handler({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2024-11-05"}})
        req = {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
               "params": {"name": "nonexistent_tool", "arguments": {}}}
        resp = handler(req)
        assert "error" in resp

    def test_unknown_method(self, handler):
        req = {"jsonrpc": "2.0", "id": 5, "method": "bogus/method"}
        resp = handler(req)
        assert "error" in resp
