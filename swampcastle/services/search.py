"""SearchService — semantic search and duplicate detection."""

from swampcastle.models.drawer import (
    DuplicateCheckQuery,
    DuplicateCheckResult,
    SearchHit,
    SearchQuery,
    SearchResponse,
)
from swampcastle.query_sanitizer import sanitize_query
from swampcastle.retrieval.hybrid import (
    merge_candidates,
    rerank_dense_candidates,
    sparse_candidates,
)
from swampcastle.storage.base import CollectionStore


class SearchService:
    def __init__(self, collection: CollectionStore, sanitizer=None):
        self._col = collection
        self._sanitizer = sanitizer or sanitize_query

    def search(self, query: SearchQuery) -> SearchResponse:
        sanitized = self._sanitizer(query.query)

        filters = []
        if query.wing:
            filters.append({"wing": query.wing})
        if query.room:
            filters.append({"room": query.room})
        if query.contributor:
            filters.append({"contributor": query.contributor})

        where = None
        if len(filters) == 1:
            where = filters[0]
        elif filters:
            where = {"$and": filters}

        do_rerank = query.lexical_rerank or query.hybrid
        dense_limit = query.limit
        if do_rerank:
            dense_limit = min(max(query.limit * 5, 20), 100)

        raw = self._col.query(
            query_texts=[sanitized["clean_query"]],
            n_results=dense_limit,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        candidates = []
        if raw["ids"] and raw["ids"][0]:
            for i, doc in enumerate(raw["documents"][0]):
                meta = raw["metadatas"][0][i]
                dist = raw["distances"][0][i]
                dense_similarity = round(1 - dist, 3)
                candidates.append(
                    {
                        "id": raw["ids"][0][i],
                        "document": doc,
                        "metadata": meta,
                        "dense_similarity": dense_similarity,
                    }
                )

        if query.hybrid:
            sparse = sparse_candidates(
                self._col,
                query=sanitized["clean_query"],
                where=where,
                context=query.context,
                limit=dense_limit,
            )
            candidates = merge_candidates(candidates, sparse)

        if do_rerank and candidates:
            candidates = rerank_dense_candidates(
                sanitized["clean_query"],
                candidates,
                context=query.context,
            )

        hits = []
        for candidate in candidates[: query.limit]:
            doc = candidate["document"]
            meta = candidate["metadata"]
            hits.append(
                SearchHit(
                    text=doc,
                    wing=meta.get("wing", ""),
                    room=meta.get("room", ""),
                    similarity=candidate["dense_similarity"],
                    source_file=meta.get("source_file"),
                    contributor=meta.get("contributor"),
                )
            )

        resp = SearchResponse(
            query=sanitized["clean_query"],
            results=hits,
            filters={
                "wing": query.wing,
                "room": query.room,
                "contributor": query.contributor,
            },
        )
        if sanitized["was_sanitized"]:
            resp.query_sanitized = True
            resp.sanitizer = {
                "method": sanitized["method"],
                "original_length": sanitized["original_length"],
                "clean_length": sanitized["clean_length"],
            }
        return resp

    def check_duplicate(self, query: DuplicateCheckQuery) -> DuplicateCheckResult:
        raw = self._col.query(
            query_texts=[query.content],
            n_results=5,
            include=["metadatas", "documents", "distances"],
        )
        matches = []
        if raw["ids"] and raw["ids"][0]:
            for i, drawer_id in enumerate(raw["ids"][0]):
                dist = raw["distances"][0][i]
                similarity = round(1 - dist, 3)
                if similarity >= query.threshold:
                    matches.append(
                        {
                            "drawer_id": drawer_id,
                            "similarity": similarity,
                            "wing": raw["metadatas"][0][i].get("wing", ""),
                            "room": raw["metadatas"][0][i].get("room", ""),
                            "preview": raw["documents"][0][i][:200],
                        }
                    )
        return DuplicateCheckResult(
            is_duplicate=len(matches) > 0,
            matches=matches,
        )
