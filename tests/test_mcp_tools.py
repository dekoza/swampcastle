"""Tests for swampcastle.mcp — rebuilt MCP server."""

import io
import json
import yaml

import pytest

from swampcastle.audit.derived import rebuild_catalog
from swampcastle.audit.origin import write_origin_manifest
from swampcastle.castle import Castle
from swampcastle.models import AddDrawerCommand, SearchQuery, SourceOrigin
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
    def test_22_tools_registered(self, tools):
        assert len(tools) == 27

    def test_all_have_schemas(self, tools):
        for name, tool in tools.items():
            assert "type" in tool.input_schema, f"{name} missing schema"

    def test_all_have_handlers(self, tools):
        for name, tool in tools.items():
            assert callable(tool.handler), f"{name} handler not callable"

    def test_tool_names_are_short(self, tools):
        for name in tools:
            assert not name.startswith("swampcastle_"), f"{name} still uses redundant prefix"

    def test_search_schema_from_model(self, tools):
        schema = tools["search"].input_schema
        assert "query" in schema["properties"]
        assert schema["required"] == ["query"]

    def test_new_audit_tool_names_registered(self, tools):
        assert "get_origin" in tools
        assert "get_curation" in tools
        assert "list_catalog_cards" in tools


class TestToolDispatch:
    def test_status_empty(self, tools):
        result = tools["status"].handler()
        assert result.total_drawers == 0

    def test_search_empty(self, tools):
        result = tools["search"].handler(SearchQuery(query="anything"))
        assert result.results == []

    def test_add_then_search(self, tools):
        add_result = tools["add_drawer"].handler(
            AddDrawerCommand(wing="test", room="arch", content="chose postgres for scale")
        )
        assert add_result.success

        search_result = tools["search"].handler(SearchQuery(query="postgres"))
        assert len(search_result.results) > 0

    def test_kg_add_then_query(self, tools):
        from swampcastle.models import AddTripleCommand, KGQueryParams

        tools["kg_add"].handler(
            AddTripleCommand(subject="Kai", predicate="works_on", object="Orion")
        )
        result = tools["kg_query"].handler(KGQueryParams(entity="Kai"))
        assert result.count == 1

    def test_aaak_spec(self, tools):
        result = tools["get_aaak_spec"].handler()
        assert "AAAK" in result

    def test_get_origin_by_origin_id(self, castle, tools):
        origin = SourceOrigin(
            origin_id="origin_test_123",
            source_kind="conversation_export",
            platform="claude-code",
            declared_transformations=["jsonl_normalize"],
            confidence="heuristic",
            source_file="/tmp/session.jsonl",
            updated_at="2026-05-07T12:00:00Z",
        )
        write_origin_manifest(castle.settings.castle_path, origin)

        result = tools["get_origin"].handler(
            tools["get_origin"].input_model(origin_id="origin_test_123")
        )

        assert result.found is True
        assert result.origin is not None
        assert result.origin.origin_id == "origin_test_123"

    def test_get_origin_by_source_file(self, castle, tools):
        source_file = str(castle.settings.castle_path / "session.jsonl")
        origin = SourceOrigin(
            origin_id="origin_test_456",
            source_kind="conversation_export",
            platform="claude-code",
            declared_transformations=["jsonl_normalize"],
            confidence="heuristic",
            source_file=source_file,
            updated_at="2026-05-07T12:00:00Z",
        )
        write_origin_manifest(castle.settings.castle_path, origin)
        castle._collection.upsert(
            documents=["hello world"],
            ids=["drawer_1"],
            metadatas=[
                {
                    "wing": "test",
                    "room": "general",
                    "source_file": source_file,
                    "origin_id": origin.origin_id,
                }
            ],
        )

        result = tools["get_origin"].handler(
            tools["get_origin"].input_model(source_file=source_file)
        )

        assert result.found is True
        assert result.origin is not None
        assert result.origin.origin_id == "origin_test_456"
        assert result.resolved_by == "source_file"

    def test_get_curation_returns_aliases_tunnels_and_wing_note(self, castle, tools):
        curation_dir = castle.settings.castle_path / ".swampcastle" / "curation"
        notes_dir = curation_dir / "wings"
        notes_dir.mkdir(parents=True)
        (curation_dir / "aliases.yaml").write_text(
            yaml.safe_dump({"personas": {"Aurora": {"canonical": "Echo"}}}),
            encoding="utf-8",
        )
        (curation_dir / "tunnels.yaml").write_text(
            yaml.safe_dump({"allow": [{"wing_a": "proj", "wing_b": "personal", "room": "auth"}]}),
            encoding="utf-8",
        )
        (notes_dir / "swampcastle.md").write_text(
            "# swampcastle\n\n"
            "## Pinned context\n- one\n\n"
            "## Open threads\n- two\n\n"
            "## Stale assumptions\n- three\n",
            encoding="utf-8",
        )

        result = tools["get_curation"].handler(
            tools["get_curation"].input_model(wing="swampcastle")
        )

        assert result.aliases.personas["Aurora"].canonical == "Echo"
        assert len(result.tunnels.allow) == 1
        assert result.wing_note is not None
        assert result.wing_note.wing == "swampcastle"

    def test_list_catalog_cards_returns_rebuilt_cards(self, castle, tools):
        castle.vault.add_drawer(
            AddDrawerCommand(
                wing="swampcastle",
                room="auth",
                content="Auth migration moved from Auth0 to Clerk.",
            )
        )
        rebuild_catalog(castle._collection, castle.settings.castle_path)

        result = tools["list_catalog_cards"].handler(
            tools["list_catalog_cards"].input_model(wing="swampcastle")
        )

        assert result.wing == "swampcastle"
        assert len(result.cards) >= 1


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
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
        resp = handler(req)
        assert resp["result"]["protocolVersion"]
        assert resp["result"]["serverInfo"]["name"] == "swampcastle"

    def test_tools_list(self, handler):
        handler(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            }
        )
        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        resp = handler(req)
        tool_names = [t["name"] for t in resp["result"]["tools"]]
        assert "search" in tool_names
        assert "get_origin" in tool_names
        assert "swampcastle_search" not in tool_names
        assert len(tool_names) == 27

    def test_tool_call_uses_canonical_name(self, handler):
        handler(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            }
        )
        req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "status", "arguments": {}},
        }
        resp = handler(req)
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "total_drawers" in content

    def test_tool_call_legacy_alias_still_works(self, handler):
        handler(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            }
        )
        req = {
            "jsonrpc": "2.0",
            "id": 31,
            "method": "tools/call",
            "params": {"name": "swampcastle_status", "arguments": {}},
        }
        resp = handler(req)
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "total_drawers" in content

    def test_unknown_tool(self, handler):
        handler(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            }
        )
        req = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}},
        }
        resp = handler(req)
        assert "error" in resp

    def test_unknown_method(self, handler):
        req = {"jsonrpc": "2.0", "id": 5, "method": "bogus/method"}
        resp = handler(req)
        assert "error" in resp

    def test_tool_call_get_origin(self, handler, castle):
        origin = SourceOrigin(
            origin_id="origin_test_789",
            source_kind="conversation_export",
            platform="claude-code",
            declared_transformations=["jsonl_normalize"],
            confidence="heuristic",
            source_file="/tmp/session.jsonl",
            updated_at="2026-05-07T12:00:00Z",
        )
        write_origin_manifest(castle.settings.castle_path, origin)

        handler(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            }
        )
        req = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "get_origin", "arguments": {"origin_id": "origin_test_789"}},
        }
        resp = handler(req)
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["found"] is True
        assert content["origin"]["origin_id"] == "origin_test_789"
