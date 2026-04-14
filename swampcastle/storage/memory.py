"""In-memory storage backends for testing.

No disk, no embeddings, no external dependencies. Provides fast,
deterministic storage for unit tests.
"""

import hashlib
import uuid
from datetime import date
from typing import Any

from .base import CollectionStore, GraphStore
from . import StorageFactory


def _match_where(meta: dict, where: dict | None) -> bool:
    """Evaluate a ChromaDB-style where clause against a metadata dict."""
    if not where:
        return True

    if "$and" in where:
        return all(_match_where(meta, clause) for clause in where["$and"])

    if "$or" in where:
        return any(_match_where(meta, clause) for clause in where["$or"])

    for key, value in where.items():
        if key.startswith("$"):
            continue
        if isinstance(value, dict):
            actual = meta.get(key)
            for op, expected in value.items():
                if op == "$gt" and not (actual is not None and actual > expected):
                    return False
                if op == "$gte" and not (actual is not None and actual >= expected):
                    return False
                if op == "$lt" and not (actual is not None and actual < expected):
                    return False
                if op == "$lte" and not (actual is not None and actual <= expected):
                    return False
                if op == "$ne" and actual == expected:
                    return False
                if op == "$eq" and actual != expected:
                    return False
        elif meta.get(key) != value:
            return False

    return True


class InMemoryCollectionStore(CollectionStore):
    """Dict-based collection. No embeddings — query uses substring match."""

    def __init__(self):
        self._docs: dict[str, dict[str, Any]] = {}

    def add(self, *, documents, ids, metadatas=None):
        self.upsert(documents=documents, ids=ids, metadatas=metadatas)

    def upsert(self, *, documents, ids, metadatas=None):
        metadatas = metadatas or [{} for _ in ids]
        for doc, id_, meta in zip(documents, ids, metadatas):
            self._docs[id_] = {"document": doc, "metadata": dict(meta)}

    def get(self, *, ids=None, where=None, limit=None, offset=None, include=None):
        if ids is not None:
            matches = [(id_, self._docs[id_]) for id_ in ids if id_ in self._docs]
        else:
            matches = [
                (id_, rec)
                for id_, rec in self._docs.items()
                if _match_where(rec["metadata"], where)
            ]

        if offset:
            matches = matches[offset:]
        if limit:
            matches = matches[:limit]

        return {
            "ids": [m[0] for m in matches],
            "documents": [m[1]["document"] for m in matches],
            "metadatas": [m[1]["metadata"] for m in matches],
        }

    def query(self, *, query_texts, n_results=5, where=None, include=None):
        query_lower = query_texts[0].lower() if query_texts else ""
        scored = []
        for id_, rec in self._docs.items():
            if not _match_where(rec["metadata"], where):
                continue
            doc_lower = rec["document"].lower()
            overlap = sum(1 for w in query_lower.split() if w in doc_lower)
            scored.append((id_, rec, overlap))

        scored.sort(key=lambda x: -x[2])
        top = scored[:n_results]

        return {
            "ids": [[s[0] for s in top]],
            "documents": [[s[1]["document"] for s in top]],
            "metadatas": [[s[1]["metadata"] for s in top]],
            "distances": [[1.0 - (s[2] / max(len(query_lower.split()), 1)) for s in top]],
        }

    def delete(self, *, ids):
        for id_ in ids:
            self._docs.pop(id_, None)

    def update(self, *, ids, documents=None, metadatas=None):
        for i, id_ in enumerate(ids):
            if id_ not in self._docs:
                continue
            if documents is not None:
                self._docs[id_]["document"] = documents[i]
            if metadatas is not None:
                self._docs[id_]["metadata"] = dict(metadatas[i])

    def count(self) -> int:
        return len(self._docs)


class InMemoryGraphStore(GraphStore):
    """Dict-based knowledge graph for testing."""

    def __init__(self):
        self._entities: dict[str, dict[str, Any]] = {}
        self._triples: list[dict[str, Any]] = []
        self._candidate_triples: dict[str, dict[str, Any]] = {}
        self._candidate_counter = 0

    def _entity_id(self, name: str) -> str:
        return name.lower().replace(" ", "_")

    def _ensure_entity(self, name: str):
        eid = self._entity_id(name)
        if eid not in self._entities:
            self._entities[eid] = {
                "id": eid,
                "name": name,
                "type": "unknown",
                "properties": {},
            }
        return eid

    def add_entity(self, *, name, entity_type="unknown", properties=None):
        eid = self._entity_id(name)
        self._entities[eid] = {
            "id": eid,
            "name": name,
            "type": entity_type,
            "properties": properties or {},
        }
        return eid

    def add_triple(
        self,
        *,
        subject,
        predicate,
        obj,
        valid_from=None,
        valid_to=None,
        confidence=1.0,
        source_closet=None,
        source_file=None,
    ):
        self._ensure_entity(subject)
        self._ensure_entity(obj)
        tid = uuid.uuid4().hex[:12]
        self._triples.append(
            {
                "id": tid,
                "subject": subject,
                "subject_id": self._entity_id(subject),
                "predicate": predicate,
                "object": obj,
                "object_id": self._entity_id(obj),
                "valid_from": valid_from,
                "valid_to": valid_to,
                "confidence": confidence,
                "source_closet": source_closet,
                "source_file": source_file,
            }
        )
        return tid

    def _is_valid_at(self, triple: dict, as_of: str) -> bool:
        vf = triple.get("valid_from")
        vt = triple.get("valid_to")
        if vf and vf > as_of:
            return False
        if vt and vt < as_of:
            return False
        return True

    def query_entity(self, *, name, as_of=None, direction="outgoing"):
        eid = self._entity_id(name)
        results = []
        for t in self._triples:
            match = False
            if direction in ("outgoing", "both") and t["subject_id"] == eid:
                match = True
            if direction in ("incoming", "both") and t["object_id"] == eid:
                match = True
            if not match:
                continue
            if as_of and not self._is_valid_at(t, as_of):
                continue
            results.append(dict(t))
        return results

    def query_relationship(self, *, predicate, as_of=None):
        results = []
        for t in self._triples:
            if t["predicate"] != predicate:
                continue
            if as_of and not self._is_valid_at(t, as_of):
                continue
            results.append(dict(t))
        return results

    def invalidate(self, *, subject, predicate, obj, ended=None):
        sid = self._entity_id(subject)
        oid = self._entity_id(obj)
        ended = ended or str(date.today())
        for t in self._triples:
            if (
                t["subject_id"] == sid
                and t["predicate"] == predicate
                and t["object_id"] == oid
                and t["valid_to"] is None
            ):
                t["valid_to"] = ended

    def timeline(self, *, entity_name=None):
        if entity_name:
            eid = self._entity_id(entity_name)
            triples = [t for t in self._triples if t["subject_id"] == eid or t["object_id"] == eid]
        else:
            triples = list(self._triples)
        return sorted(triples, key=lambda t: t.get("valid_from") or "")

    def stats(self):
        current = sum(1 for t in self._triples if t["valid_to"] is None)
        expired = sum(1 for t in self._triples if t["valid_to"] is not None)
        preds = {t["predicate"] for t in self._triples}
        return {
            "entities": len(self._entities),
            "triples": len(self._triples),
            "current_facts": current,
            "expired_facts": expired,
            "relationship_types": sorted(preds),
        }

    def propose_triple(
        self,
        *,
        subject_text,
        predicate,
        object_text,
        confidence,
        modality,
        polarity,
        evidence_drawer_id,
        evidence_text,
        extractor_version,
        valid_from=None,
        valid_to=None,
        source_file=None,
        wing=None,
        room=None,
    ):
        fingerprint = hashlib.sha256(
            (
                f"{subject_text}\x00{predicate}\x00{object_text}\x00{modality}\x00{polarity}\x00"
                f"{valid_from or ''}\x00{valid_to or ''}\x00{evidence_drawer_id}\x00{evidence_text}\x00"
                f"{source_file or ''}\x00{wing or ''}\x00{room or ''}"
            ).encode()
        ).hexdigest()[:16]
        candidate_id = f"cand_{fingerprint}"
        existing = self._candidate_triples.get(candidate_id)
        status = existing["status"] if existing is not None else "proposed"
        reviewed_at = existing.get("reviewed_at") if existing is not None else None
        created_at = existing.get("created_at") if existing is not None else None
        self._candidate_triples[candidate_id] = {
            "id": candidate_id,
            "subject_text": subject_text,
            "predicate": predicate,
            "object_text": object_text,
            "confidence": confidence,
            "modality": modality,
            "polarity": polarity,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "evidence_drawer_id": evidence_drawer_id,
            "evidence_text": evidence_text,
            "source_file": source_file,
            "wing": wing,
            "room": room,
            "status": status,
            "extractor_version": extractor_version,
            "created_at": created_at,
            "reviewed_at": reviewed_at,
        }
        return candidate_id

    def get_candidate_triple(self, *, candidate_id):
        row = self._candidate_triples.get(candidate_id)
        return dict(row) if row is not None else None

    def list_candidate_triples(
        self,
        *,
        status=None,
        predicate=None,
        min_confidence=None,
        wing=None,
        room=None,
        limit=50,
        offset=0,
    ):
        rows = list(self._candidate_triples.values())
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        if predicate is not None:
            rows = [row for row in rows if row["predicate"] == predicate]
        if min_confidence is not None:
            rows = [row for row in rows if row["confidence"] >= min_confidence]
        if wing is not None:
            rows = [row for row in rows if row.get("wing") == wing]
        if room is not None:
            rows = [row for row in rows if row.get("room") == room]
        rows = rows[offset : offset + limit]
        return [dict(row) for row in rows]

    def set_candidate_status(self, *, candidate_id, status, reviewed_at=None):
        row = self._candidate_triples.get(candidate_id)
        if row is None:
            return False
        row["status"] = status
        row["reviewed_at"] = reviewed_at
        return True

    def close(self):
        pass


class InMemoryStorageFactory(StorageFactory):
    """Factory that creates in-memory stores. Same name = same instance."""

    def __init__(self):
        self._collections: dict[str, InMemoryCollectionStore] = {}
        self._graph: InMemoryGraphStore | None = None

    def open_collection(self, name: str) -> InMemoryCollectionStore:
        if name not in self._collections:
            self._collections[name] = InMemoryCollectionStore()
        return self._collections[name]

    def open_graph(self) -> InMemoryGraphStore:
        if self._graph is None:
            self._graph = InMemoryGraphStore()
        return self._graph
