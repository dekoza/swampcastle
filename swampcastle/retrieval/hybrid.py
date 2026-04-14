"""Lightweight lexical reranking for dense search candidates.

This is an incremental step toward hybrid retrieval. It does **not** replace
vector retrieval for candidate generation. Instead it reranks the dense
candidates using lexical overlap with the query, plus optional non-embedded
background context.
"""

from __future__ import annotations

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
