"""SearchService — semantic search and duplicate detection."""

from swampcastle.models.drawer import (
    DuplicateCheckQuery,
    DuplicateCheckResult,
    SearchHit,
    SearchQuery,
    SearchResponse,
)
from swampcastle.query_sanitizer import sanitize_query
from swampcastle.storage.base import CollectionStore


class SearchService:
    def __init__(self, collection: CollectionStore, sanitizer=None):
        self._col = collection
        self._sanitizer = sanitizer or sanitize_query

    def search(self, query: SearchQuery) -> SearchResponse:
        sanitized = self._sanitizer(query.query)

        where = {}
        if query.wing:
            where["wing"] = query.wing
        if query.room:
            if where:
                where = {"$and": [{"wing": query.wing}, {"room": query.room}]}
            else:
                where["room"] = query.room

        raw = self._col.query(
            query_texts=[sanitized["clean_query"]],
            n_results=query.limit,
            where=where or None,
            include=["documents", "metadatas", "distances"],
        )

        hits = []
        if raw["ids"] and raw["ids"][0]:
            for i, doc in enumerate(raw["documents"][0]):
                meta = raw["metadatas"][0][i]
                dist = raw["distances"][0][i]
                hits.append(
                    SearchHit(
                        text=doc,
                        wing=meta.get("wing", ""),
                        room=meta.get("room", ""),
                        similarity=round(1 - dist, 3),
                        source_file=meta.get("source_file"),
                    )
                )

        resp = SearchResponse(
            query=sanitized["clean_query"],
            results=hits,
            filters={"wing": query.wing, "room": query.room},
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
