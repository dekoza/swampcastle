"""Tests for swampcastle.models — Pydantic I/O models."""

import pytest

from swampcastle.models import (
    AddDrawerCommand,
    AddTripleCommand,
    DiaryWriteCommand,
    DuplicateCheckQuery,
    KGQueryParams,
    SearchQuery,
    SearchResponse,
    SearchHit,
    StatusResponse,
    VersionVector,
)


class TestSearchQuery:
    def test_defaults(self):
        q = SearchQuery(query="test")
        assert q.limit == 5
        assert q.wing is None
        assert q.room is None

    def test_max_length(self):
        with pytest.raises(Exception):
            SearchQuery(query="x" * 501)

    def test_limit_bounds(self):
        with pytest.raises(Exception):
            SearchQuery(query="test", limit=0)
        with pytest.raises(Exception):
            SearchQuery(query="test", limit=101)

    def test_valid_query(self):
        q = SearchQuery(query="auth decisions", wing="myapp", limit=10)
        assert q.query == "auth decisions"
        assert q.wing == "myapp"


class TestAddDrawerCommand:
    def test_valid(self):
        cmd = AddDrawerCommand(wing="myapp", room="auth", content="decision text")
        assert cmd.wing == "myapp"
        assert cmd.added_by == "mcp"

    def test_drawer_id_deterministic(self):
        cmd = AddDrawerCommand(wing="w", room="r", content="hello")
        id1 = cmd.drawer_id()
        id2 = cmd.drawer_id()
        assert id1 == id2
        assert id1.startswith("drawer_w_r_")

    def test_different_content_different_id(self):
        a = AddDrawerCommand(wing="w", room="r", content="aaa")
        b = AddDrawerCommand(wing="w", room="r", content="bbb")
        assert a.drawer_id() != b.drawer_id()

    def test_wing_validation_rejects_path_traversal(self):
        with pytest.raises(Exception):
            AddDrawerCommand(wing="../etc", room="r", content="x")

    def test_wing_validation_rejects_slashes(self):
        with pytest.raises(Exception):
            AddDrawerCommand(wing="a/b", room="r", content="x")

    def test_wing_validation_rejects_null_bytes(self):
        with pytest.raises(Exception):
            AddDrawerCommand(wing="a\x00b", room="r", content="x")

    def test_content_validation_rejects_empty(self):
        with pytest.raises(Exception):
            AddDrawerCommand(wing="w", room="r", content="")

    def test_content_validation_rejects_null_bytes(self):
        with pytest.raises(Exception):
            AddDrawerCommand(wing="w", room="r", content="hello\x00world")

    def test_content_max_length(self):
        with pytest.raises(Exception):
            AddDrawerCommand(wing="w", room="r", content="x" * 100_001)


class TestKGQueryParams:
    def test_defaults(self):
        p = KGQueryParams(entity="Kai")
        assert p.direction == "both"
        assert p.as_of is None

    def test_direction_validation(self):
        with pytest.raises(Exception):
            KGQueryParams(entity="Kai", direction="sideways")


class TestAddTripleCommand:
    def test_valid(self):
        cmd = AddTripleCommand(subject="Kai", predicate="works_on", object="Orion")
        assert cmd.subject == "Kai"

    def test_optional_fields(self):
        cmd = AddTripleCommand(
            subject="A", predicate="rel", object="B",
            valid_from="2025-01-01", source_closet="c1",
        )
        assert cmd.valid_from == "2025-01-01"


class TestDuplicateCheckQuery:
    def test_defaults(self):
        q = DuplicateCheckQuery(content="test")
        assert q.threshold == 0.9

    def test_threshold_bounds(self):
        with pytest.raises(Exception):
            DuplicateCheckQuery(content="test", threshold=1.5)
        with pytest.raises(Exception):
            DuplicateCheckQuery(content="test", threshold=-0.1)


class TestDiaryWriteCommand:
    def test_defaults(self):
        cmd = DiaryWriteCommand(agent_name="reviewer", entry="found bug")
        assert cmd.topic == "general"


class TestVersionVector:
    def test_empty(self):
        vv = VersionVector()
        assert vv.get("node1") == 0

    def test_update_and_get(self):
        vv = VersionVector()
        vv.update("node1", 5)
        assert vv.get("node1") == 5

    def test_update_ignores_lower(self):
        vv = VersionVector()
        vv.update("node1", 10)
        vv.update("node1", 3)
        assert vv.get("node1") == 10


class TestSerialization:
    def test_search_response_roundtrip(self):
        resp = SearchResponse(
            query="test",
            results=[SearchHit(text="found", wing="w", room="r", similarity=0.9)],
        )
        data = resp.model_dump()
        restored = SearchResponse(**data)
        assert restored.results[0].text == "found"

    def test_status_response_roundtrip(self):
        resp = StatusResponse(
            total_drawers=42, wings={"w": 42}, rooms={"r": 42},
            castle_path="/tmp", protocol="proto", aaak_dialect="aaak",
        )
        data = resp.model_dump()
        restored = StatusResponse(**data)
        assert restored.total_drawers == 42


class TestJsonSchema:
    def test_search_query_schema(self):
        schema = SearchQuery.model_json_schema()
        assert "properties" in schema
        assert "query" in schema["properties"]

    def test_add_drawer_schema(self):
        schema = AddDrawerCommand.model_json_schema()
        assert "wing" in schema["properties"]
        assert "content" in schema["properties"]
