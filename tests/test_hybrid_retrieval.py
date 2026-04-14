"""Tests for lexical reranking of dense search candidates.

This is the first incremental step toward hybrid retrieval: keep dense vector
retrieval for candidate generation, then optionally rerank those candidates by
lexical overlap with the query (and optional context, which is *not* embedded).
"""

from __future__ import annotations

from swampcastle.models.drawer import SearchQuery
from swampcastle.services.search import SearchService


class _FakeCollection:
    def __init__(self, raw):
        self._raw = raw
        self.last_n_results = None

    def query(self, *, query_texts, n_results=5, where=None, include=None):
        self.last_n_results = n_results
        return self._raw


def _raw_results(documents, metadatas, distances):
    ids = [[f"id_{i}" for i in range(len(documents))]]
    return {
        "ids": ids,
        "documents": [documents],
        "metadatas": [metadatas],
        "distances": [distances],
    }


def _meta(wing="w", room="r"):
    return {"wing": wing, "room": room}


def test_search_without_lexical_rerank_preserves_dense_order():
    col = _FakeCollection(
        _raw_results(
            documents=[
                "general migration discussion with lots of context",
                "auth migration from Auth0 to Clerk with rollback notes",
            ],
            metadatas=[_meta(), _meta()],
            distances=[0.10, 0.11],  # doc0 slightly better dense score
        )
    )
    svc = SearchService(col)

    result = svc.search(SearchQuery(query="auth migration clerk", limit=2))

    assert result.results[0].text.startswith("general migration discussion")
    assert col.last_n_results == 2


def test_search_with_lexical_rerank_promotes_exact_match():
    col = _FakeCollection(
        _raw_results(
            documents=[
                "general migration discussion with lots of context",
                "auth migration from Auth0 to Clerk with rollback notes",
                "billing migration plan",
            ],
            metadatas=[_meta(), _meta(), _meta()],
            distances=[0.10, 0.11, 0.12],  # dense order is intentionally wrong
        )
    )
    svc = SearchService(col)

    result = svc.search(SearchQuery(query="auth migration clerk", limit=2, lexical_rerank=True))

    assert result.results[0].text.startswith("auth migration from Auth0 to Clerk")
    # lexical rerank should ask dense retrieval for a wider candidate pool
    assert col.last_n_results > 2


def test_context_is_used_for_lexical_rerank_but_not_required():
    col = _FakeCollection(
        _raw_results(
            documents=[
                "migration decision notes",
                "migration decision notes for postgres sharding",
            ],
            metadatas=[_meta(), _meta()],
            distances=[0.10, 0.11],
        )
    )
    svc = SearchService(col)

    result = svc.search(
        SearchQuery(
            query="migration decision",
            context="postgres sharding",
            limit=2,
            lexical_rerank=True,
        )
    )

    assert result.results[0].text.endswith("postgres sharding")
