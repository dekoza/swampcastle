"""Lightweight lexical reranking and sparse candidate generation.

This is an incremental step toward hybrid retrieval. It does not replace the
vector store for primary candidate generation, but it can:
- rerank dense candidates lexically
- add sparse lexical candidates collected via CollectionStore.get()
"""

from __future__ import annotations

import heapq
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")
_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "what",
    "when",
    "where",
    "which",
    "while",
    "have",
    "has",
    "had",
    "was",
    "were",
    "are",
    "is",
    "how",
    "why",
    "all",
    "our",
    "your",
    "their",
    "about",
    "show",
    "tell",
    "please",
    "does",
    "did",
    "using",
}


def _tokenize(text: str | None) -> list[str]:
    if not text:
        return []
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOP_WORDS]


def lexical_score(query: str, document: str, context: str | None = None) -> float:
    """Return lexical coverage score in [0,1].

    Query tokens count full weight. Context tokens count half weight because
    they are useful for reranking but should not overpower the explicit query.
    """
    query_tokens = _tokenize(query)
    context_tokens = _tokenize(context)
    if not query_tokens and not context_tokens:
        return 0.0

    doc_counts = Counter(_tokenize(document))
    weights: dict[str, float] = {}
    for token in query_tokens:
        weights[token] = max(weights.get(token, 0.0), 1.0)
    for token in context_tokens:
        weights[token] = max(weights.get(token, 0.0), 0.5)

    total_weight = sum(weights.values())
    if total_weight == 0:
        return 0.0

    matched_weight = sum(
        weight for token, weight in weights.items() if doc_counts.get(token, 0) > 0
    )
    return matched_weight / total_weight


def rerank_dense_candidates(
    query: str,
    candidates: list[dict],
    *,
    context: str | None = None,
) -> list[dict]:
    """Return candidates sorted by lexical score then dense similarity."""
    scored = []
    for idx, candidate in enumerate(candidates):
        score = lexical_score(query, candidate.get("document", ""), context=context)
        scored.append((score, candidate.get("dense_similarity", 0.0), -idx, candidate))

    scored.sort(reverse=True)
    return [candidate for _, _, _, candidate in scored]


_DEF_SPARSE_SCAN_LIMIT = 5000
_DEF_SPARSE_BATCH_SIZE = 500


def sparse_candidates(
    collection,
    *,
    query: str,
    where: dict | None,
    context: str | None = None,
    limit: int = 20,
    scan_limit: int = _DEF_SPARSE_SCAN_LIMIT,
    batch_size: int = _DEF_SPARSE_BATCH_SIZE,
) -> list[dict]:
    """Return top lexical candidates by scanning documents from CollectionStore.

    This is intentionally simple and backend-agnostic. It is slower than a real
    sparse index but works immediately on every existing backend.
    """
    heap: list[tuple[float, int, dict]] = []
    seen = 0
    counter = 0
    offset = 0

    while seen < scan_limit:
        batch = collection.get(
            where=where,
            limit=min(batch_size, scan_limit - seen),
            offset=offset,
            include=["documents", "metadatas"],
        )
        ids = batch.get("ids", [])
        if not ids:
            break

        for doc_id, doc, meta in zip(ids, batch.get("documents", []), batch.get("metadatas", [])):
            score = lexical_score(query, doc, context=context)
            if score <= 0:
                counter += 1
                continue
            candidate = {
                "id": doc_id,
                "document": doc,
                "metadata": meta,
                "dense_similarity": 0.0,
            }
            heapq.heappush(heap, (score, counter, candidate))
            counter += 1
            if len(heap) > limit:
                heapq.heappop(heap)

        seen += len(ids)
        offset += len(ids)

    items = sorted(heap, key=lambda x: (x[0], -x[1]), reverse=True)
    return [candidate for _, _, candidate in items]


def merge_candidates(*candidate_lists: list[dict]) -> list[dict]:
    """Merge candidate lists by id or fallback document text."""
    merged: dict[str, dict] = {}
    for candidates in candidate_lists:
        for candidate in candidates:
            key = candidate.get("id") or candidate.get("document", "")
            existing = merged.get(key)
            if existing is None:
                merged[key] = dict(candidate)
                continue
            existing["dense_similarity"] = max(
                existing.get("dense_similarity", 0.0),
                candidate.get("dense_similarity", 0.0),
            )
            if not existing.get("metadata") and candidate.get("metadata"):
                existing["metadata"] = candidate["metadata"]
            if not existing.get("document") and candidate.get("document"):
                existing["document"] = candidate["document"]
    return list(merged.values())
