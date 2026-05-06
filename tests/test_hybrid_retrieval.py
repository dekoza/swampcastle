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


def _meta(wing="w", room="r", **extra):
    meta = {"wing": wing, "room": room}
    meta.update(extra)
    return meta


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


class _HybridCollection(_FakeCollection):
    def __init__(self, raw, sparse_docs):
        super().__init__(raw)
        self._sparse_docs = sparse_docs
        self.get_calls = []

    def get(self, *, ids=None, where=None, limit=None, offset=None, include=None):
        self.get_calls.append(
            {"limit": limit, "offset": offset, "include": include, "where": where}
        )
        start = offset or 0
        end = start + (limit or len(self._sparse_docs))
        batch = self._sparse_docs[start:end]
        return {
            "ids": [row["id"] for row in batch],
            "documents": [row["document"] for row in batch],
            "metadatas": [row["metadata"] for row in batch],
        }


def test_search_with_hybrid_adds_sparse_candidates_missing_from_dense_results():
    col = _HybridCollection(
        raw=_raw_results(
            documents=[
                "general migration discussion",
                "billing migration plan",
            ],
            metadatas=[_meta(), _meta()],
            distances=[0.10, 0.11],
        ),
        sparse_docs=[
            {"id": "dense_0", "document": "general migration discussion", "metadata": _meta()},
            {"id": "dense_1", "document": "billing migration plan", "metadata": _meta()},
            {
                "id": "sparse_only",
                "document": "auth migration from Auth0 to Clerk with rollback notes",
                "metadata": _meta(),
            },
        ],
    )
    svc = SearchService(col)

    result = svc.search(SearchQuery(query="auth migration clerk", limit=2, hybrid=True))

    assert result.results[0].text.startswith("auth migration from Auth0 to Clerk")
    assert col.get_calls, "Hybrid retrieval should scan lexical candidates via collection.get()"


def test_search_with_explain_reports_dense_path_and_origin_metadata():
    col = _FakeCollection(
        _raw_results(
            documents=["auth migration from Auth0 to Clerk"],
            metadatas=[
                _meta(
                    source_file="/tmp/session.jsonl",
                    origin_id="origin_123",
                    source_kind="conversation_export",
                    source_platform="claude-code",
                )
            ],
            distances=[0.10],
        )
    )
    svc = SearchService(col)

    result = svc.search(SearchQuery(query="auth migration", limit=1, explain=True))

    hit = result.results[0]
    assert hit.matched_via == "dense"
    assert hit.dense_similarity == 0.9
    assert hit.lexical_score is None
    assert hit.origin_id == "origin_123"
    assert hit.source_kind == "conversation_export"
    assert hit.source_platform == "claude-code"


def test_search_with_lexical_rerank_explain_reports_lexical_details():
    col = _FakeCollection(
        _raw_results(
            documents=[
                "general migration discussion with lots of context",
                "auth migration from Auth0 to Clerk with rollback notes",
            ],
            metadatas=[_meta(), _meta()],
            distances=[0.10, 0.11],
        )
    )
    svc = SearchService(col)

    result = svc.search(
        SearchQuery(query="auth migration clerk", limit=1, lexical_rerank=True, explain=True)
    )

    hit = result.results[0]
    assert hit.matched_via == "lexical"
    assert hit.dense_similarity == 0.89
    assert hit.lexical_score and hit.lexical_score > 0
    assert "lexical_rerank" in hit.boosts


def test_search_with_hybrid_explain_reports_hybrid_path():
    col = _HybridCollection(
        raw=_raw_results(
            documents=["general migration discussion"],
            metadatas=[_meta()],
            distances=[0.10],
        ),
        sparse_docs=[
            {"id": "dense_0", "document": "general migration discussion", "metadata": _meta()},
            {
                "id": "sparse_only",
                "document": "auth migration from Auth0 to Clerk with rollback notes",
                "metadata": _meta(source_kind="conversation_export"),
            },
        ],
    )
    svc = SearchService(col)

    result = svc.search(
        SearchQuery(query="auth migration clerk", limit=1, hybrid=True, explain=True)
    )

    hit = result.results[0]
    assert hit.matched_via == "hybrid"
    assert hit.lexical_score and hit.lexical_score > 0
    assert "hybrid_candidate_merge" in hit.boosts
    assert hit.source_kind == "conversation_export"
