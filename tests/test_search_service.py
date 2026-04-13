"""Tests for SearchService."""

import pytest

from swampcastle.models.drawer import DuplicateCheckQuery, SearchQuery
from swampcastle.services.search import SearchService
from swampcastle.storage.memory import InMemoryCollectionStore


@pytest.fixture
def col():
    c = InMemoryCollectionStore()
    c.upsert(
        documents=[
            "we chose postgres for horizontal scaling",
            "auth migration from Auth0 to Clerk",
            "graphql vs rest api discussion",
        ],
        ids=["1", "2", "3"],
        metadatas=[
            {"wing": "backend", "room": "database", "contributor": "dekoza"},
            {"wing": "backend", "room": "auth", "contributor": "sarah"},
            {"wing": "api", "room": "design", "contributor": "dekoza"},
        ],
    )
    return c


@pytest.fixture
def svc(col):
    return SearchService(col)


class TestSearch:
    def test_basic(self, svc):
        r = svc.search(SearchQuery(query="postgres scaling"))
        assert len(r.results) > 0
        assert "postgres" in r.results[0].text.lower()

    def test_empty_castle(self):
        svc = SearchService(InMemoryCollectionStore())
        r = svc.search(SearchQuery(query="anything"))
        assert r.results == []

    def test_wing_filter(self, svc):
        r = svc.search(SearchQuery(query="api", wing="api"))
        assert all(h.wing == "api" for h in r.results)

    def test_sanitizer_called(self):
        called = {}

        def mock_sanitizer(q):
            called["query"] = q
            return {
                "clean_query": q,
                "was_sanitized": False,
                "original_length": len(q),
                "clean_length": len(q),
                "method": "passthrough",
            }

        col = InMemoryCollectionStore()
        svc = SearchService(col, sanitizer=mock_sanitizer)
        svc.search(SearchQuery(query="test"))
        assert called["query"] == "test"

    def test_sanitized_response(self):
        def sanitizer(q):
            return {
                "clean_query": "cleaned",
                "was_sanitized": True,
                "original_length": 500,
                "clean_length": 7,
                "method": "question_extraction",
            }

        col = InMemoryCollectionStore()
        svc = SearchService(col, sanitizer=sanitizer)
        r = svc.search(SearchQuery(query="x" * 500))
        assert r.query_sanitized is True
        assert r.sanitizer["method"] == "question_extraction"

    def test_response_has_filters(self, svc):
        r = svc.search(SearchQuery(query="test", wing="backend"))
        assert r.filters["wing"] == "backend"


class TestCheckDuplicate:
    def test_finds_duplicate(self, svc):
        r = svc.check_duplicate(
            DuplicateCheckQuery(
                content="we chose postgres for horizontal scaling",
                threshold=0.5,
            )
        )
        assert r.is_duplicate is True
        assert len(r.matches) > 0

    def test_no_duplicate(self, svc):
        r = svc.check_duplicate(
            DuplicateCheckQuery(
                content="completely unrelated quantum physics discussion",
                threshold=0.99,
            )
        )
        assert r.is_duplicate is False

    def test_contributor_filter(self, svc):
        r = svc.search(SearchQuery(query="api", contributor="dekoza"))
        assert r.filters["contributor"] == "dekoza"
        assert r.results
        assert all(h.contributor == "dekoza" for h in r.results)

    def test_search_hit_exposes_contributor(self, svc):
        r = svc.search(SearchQuery(query="auth"))
        assert r.results[0].contributor in {"dekoza", "sarah"}
