"""
sync.py — Sync engine for multi-device SwampCastle replication.

Hub-and-spoke model with version vectors.  Each node writes locally with
its own node_id + monotonic seq.  On sync, nodes exchange records the
other hasn't seen yet.

Changesets are lists of records with their full metadata (including
node_id, seq, updated_at).  The version vector is a dict mapping
node_id → highest_seq_seen_from_that_node.

Conflict resolution:
  - New records (id never seen): accepted unconditionally.
  - Same id on both sides: last-writer-wins by updated_at, node_id tiebreak.
"""

from __future__ import annotations

import logging

from .models.sync import (
    ChangeSet,
    MergeResult,
    SyncRecord,
    VersionVector,
    VersionVectorStore,
)
from .sync_meta import NodeIdentity, get_identity

logger = logging.getLogger("swampcastle.sync")


# ── Sync engine ───────────────────────────────────────────────────────────────


class SyncEngine:
    """Extracts and applies changesets against a palace collection.

    Usage (push side — laptop sending to server):
        engine = SyncEngine(collection, identity, vv_path)
        changeset = engine.get_changes_since(remote_vv)
        # ... send changeset to server ...

    Usage (pull side — applying records from the other node):
        result = engine.apply_changes(changeset)
    """

    def __init__(self, collection, identity: NodeIdentity = None, vv_path: str = None):
        self._col = collection
        self._identity = identity or get_identity()
        self._vv_store = VersionVectorStore(path=vv_path)
        if not self._vv_store.to_dict() and hasattr(self._col, "count") and self._col.count():
            self._rebuild_vv_from_collection()

    def _rebuild_vv_from_collection(self) -> None:
        """Scan collection metadata to reconstruct a missing or empty VV.

        Runs once at startup when the collection has records but no VV file
        exists — the typical case after 'mine'/'gather' populates a palace
        without going through apply_changes.  After rebuilding, the VV is
        persisted so future startups skip this scan.
        """
        import logging

        logger = logging.getLogger("swampcastle.sync")
        logger.info("VV empty but collection non-empty — rebuilding VV from metadata")
        result = self._col.get(where=None, limit=None, include=["metadatas"])
        for meta in result.get("metadatas", []):
            node_id = meta.get("node_id", "")
            seq = meta.get("seq", 0)
            if isinstance(seq, str):
                seq = int(seq) if seq else 0
            if node_id and seq:
                self._vv_store.update(node_id, seq)
        if self._vv_store.to_dict():
            self._vv_store.save()
            logger.info("VV rebuilt: %s", self._vv_store.to_dict())

    @property
    def version_vector(self) -> dict[str, int]:
        return self._vv_store.to_dict()

    def _build_changes_filter(self, remote_vv: dict[str, int]) -> dict | None:
        """Build a where clause that selects records the remote hasn't seen.

        Uses indexed node_id/seq columns so LanceDB can filter at the
        storage layer instead of scanning every record into Python.
        """
        if not remote_vv:
            # Remote has seen nothing — return all records that have a seq
            return {"seq": {"$gt": 0}}

        # For each known node: records where seq > what remote has seen.
        # Plus: records from any node NOT in remote_vv.
        # $nin translates to a single NOT IN (...) clause, which LanceDB
        # and PostgreSQL can evaluate efficiently against an indexed column.
        known_nodes = list(remote_vv.keys())
        clauses = [
            {"$and": [{"node_id": node_id}, {"seq": {"$gt": seen_seq}}]}
            for node_id, seen_seq in remote_vv.items()
        ]
        clauses.append(
            {"$and": [{"seq": {"$gt": 0}}, {"node_id": {"$nin": known_nodes}}]}
        )
        return {"$or": clauses}

    def count_changes_since(self, remote_vv: dict[str, int]) -> int:
        """Return the total number of records the remote hasn't seen.

        Uses an IDs-only fetch to avoid loading documents and embeddings.
        """
        where = self._build_changes_filter(remote_vv)
        result = self._col.get(where=where, limit=None, include=[])
        return len(result["ids"])

    def get_changes_since(
        self,
        remote_vv: dict[str, int],
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> ChangeSet:
        """Get all records that the remote hasn't seen.

        limit/offset: paginate over the result set. When limit is given,
        check whether the caller should fetch more by comparing
        len(changeset.records) == limit (standard "saturated page" heuristic).

        Uses indexed node_id/seq columns for efficient filtering.
        Essential for hub-and-spoke: the hub relays records from any node.
        """
        our_node = self._identity.node_id
        where = self._build_changes_filter(remote_vv)

        effective_limit = limit if limit is not None else 100_000
        records = self._col.get(
            where=where,
            limit=effective_limit,
            offset=offset if offset > 0 else None,
            include=["documents", "metadatas", "embeddings"],
        )
        embeddings = list(records.get("embeddings", []))
        if len(embeddings) < len(records["ids"]):
            embeddings.extend([None] * (len(records["ids"]) - len(embeddings)))

        changeset = ChangeSet(source_node=our_node)
        for id_, doc, meta, emb in zip(
            records["ids"],
            records["documents"],
            records["metadatas"],
            embeddings,
        ):
            changeset.records.append(
                SyncRecord(id=id_, document=doc, metadata=meta, embedding=emb)
            )

        return changeset

    def apply_changes(self, changeset: ChangeSet) -> MergeResult:
        """Apply a changeset from a remote node.

        Conflict resolution: last-writer-wins by updated_at, then node_id.
        """
        result = MergeResult()

        if not changeset.records:
            return result

        # Batch-check which IDs already exist locally
        incoming_ids = [r.id for r in changeset.records]
        existing = self._col.get(ids=incoming_ids, include=["metadatas"])
        existing_map = {}
        for eid, emeta in zip(existing.get("ids", []), existing.get("metadatas", [])):
            existing_map[eid] = emeta

        to_upsert_docs = []
        to_upsert_ids = []
        to_upsert_metas = []
        to_upsert_embs = []
        winner_ids: list[str] = []

        for rec in changeset.records:
            local_meta = existing_map.get(rec.id)

            if local_meta is None:
                # New record — accept
                to_upsert_docs.append(rec.document)
                to_upsert_ids.append(rec.id)
                to_upsert_metas.append(rec.metadata)
                to_upsert_embs.append(rec.embedding)
                result.accepted += 1
            else:
                # Conflict — last-writer-wins
                if self._remote_wins(rec.metadata, local_meta):
                    to_upsert_docs.append(rec.document)
                    to_upsert_ids.append(rec.id)
                    to_upsert_metas.append(rec.metadata)
                    to_upsert_embs.append(rec.embedding)
                    result.accepted += 1
                else:
                    winner_ids.append(rec.id)
                    result.rejected_conflicts += 1

        if to_upsert_ids:
            # Split: records with embeddings vs those needing re-embedding
            with_emb_docs, with_emb_ids, with_emb_metas, with_emb_vecs = [], [], [], []
            without_emb_docs, without_emb_ids, without_emb_metas = [], [], []

            for doc, id_, meta, emb in zip(
                to_upsert_docs, to_upsert_ids, to_upsert_metas, to_upsert_embs
            ):
                if emb is not None:
                    with_emb_docs.append(doc)
                    with_emb_ids.append(id_)
                    with_emb_metas.append(meta)
                    with_emb_vecs.append(emb)
                else:
                    without_emb_docs.append(doc)
                    without_emb_ids.append(id_)
                    without_emb_metas.append(meta)

            if with_emb_ids:
                self._col.upsert(
                    documents=with_emb_docs,
                    ids=with_emb_ids,
                    metadatas=with_emb_metas,
                    embeddings=with_emb_vecs,
                    _raw=True,
                )
            if without_emb_ids:
                self._col.upsert(
                    documents=without_emb_docs,
                    ids=without_emb_ids,
                    metadatas=without_emb_metas,
                    _raw=True,
                )

        # Fetch full data for locally-winning conflict records so the caller
        # can return them to the remote side (remote keeps its stale version
        # otherwise — the seq-based pull filter won't re-deliver them).
        if winner_ids:
            won = self._col.get(
                ids=winner_ids,
                include=["documents", "metadatas", "embeddings"],
            )
            won_embs = list(won.get("embeddings") or [])
            if len(won_embs) < len(won["ids"]):
                won_embs.extend([None] * (len(won["ids"]) - len(won_embs)))
            for wid, wdoc, wmeta, wemb in zip(
                won["ids"], won["documents"], won["metadatas"], won_embs
            ):
                result.winning_records.append(
                    SyncRecord(id=wid, document=wdoc, metadata=wmeta, embedding=wemb)
                )

        # Advance our version vector
        self._vv_store.update_from_records(changeset.records)

        return result

    @staticmethod
    def _parse_ts(raw: str):
        """Parse an ISO 8601 timestamp to a timezone-aware datetime."""
        from datetime import datetime, timezone

        if not raw:
            return datetime.min.replace(tzinfo=timezone.utc)
        # Handle 'Z' suffix
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _remote_wins(self, remote_meta: dict, local_meta: dict) -> bool:
        """Return True if the remote record should overwrite the local one.

        Comparison: updated_at descending (parsed as UTC), then node_id tiebreak.

        On exact timestamp tie the lexicographically higher node_id wins.
        This is arbitrary but deterministic — both sides reach the same
        conclusion without coordination.  Node IDs are stable across
        restarts (persisted in ~/.swampcastle/node_id).
        """
        r_time = self._parse_ts(remote_meta.get("updated_at", ""))
        l_time = self._parse_ts(local_meta.get("updated_at", ""))

        if r_time > l_time:
            return True
        if r_time < l_time:
            return False

        # Tiebreak: higher node_id wins (deterministic)
        r_node = remote_meta.get("node_id", "")
        l_node = local_meta.get("node_id", "")
        return r_node > l_node
