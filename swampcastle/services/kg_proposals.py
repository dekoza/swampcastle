"""KG proposal service — proposal-first candidate triple workflow."""

from __future__ import annotations

from datetime import date, datetime

from swampcastle.mining.extractors import extract_candidate_triples_from_text
from swampcastle.models.kg_candidates import (
    CandidateReviewCommand,
    CandidateReviewResult,
    CandidateTriple,
    CandidateTripleFilter,
)
from swampcastle.storage.base import CollectionStore, GraphStore
from swampcastle.wal import WalWriter


_EXCLUSIVE_PREDICATES = {
    "uses",
    "migrated_to",
    "deployed_to",
    "owned_by",
    "replaced_by",
    "superseded_by",
}


class KGProposalService:
    def __init__(self, graph: GraphStore, collection: CollectionStore, wal: WalWriter):
        self._graph = graph
        self._collection = collection
        self._wal = wal

    def _find_conflicting_objects(
        self,
        *,
        subject_text: str,
        predicate: str,
        object_text: str,
        modality: str = "asserted",
        polarity: str = "positive",
    ) -> list[str]:
        if predicate not in _EXCLUSIVE_PREDICATES:
            return []
        if modality != "asserted" or polarity != "positive":
            return []

        rows = self._graph.query_entity(name=subject_text, direction="outgoing")
        conflicts = []
        for row in rows:
            if row.get("predicate") != predicate:
                continue
            is_current = row.get("current")
            if is_current is None:
                is_current = row.get("valid_to") is None
            if not is_current:
                continue
            existing_object = row.get("object")
            if existing_object and existing_object != object_text:
                conflicts.append(existing_object)
        return sorted(set(conflicts))

    def extract_from_drawers(
        self,
        *,
        wing: str | None = None,
        room: str | None = None,
        dry_run: bool = True,
        limit: int = 0,
        extractor_version: str = "rules-v1",
    ) -> list[CandidateTriple]:
        where = {}
        if wing:
            where["wing"] = wing
        if room:
            where["room"] = room

        offset = 0
        batch_size = 500
        seen_drawers = 0
        extracted: list[CandidateTriple] = []

        while True:
            remaining = batch_size
            if limit > 0:
                remaining = min(batch_size, limit - seen_drawers)
                if remaining <= 0:
                    break

            batch = self._collection.get(
                where=where or None,
                limit=remaining,
                offset=offset,
                include=["documents", "metadatas"],
            )
            ids = batch.get("ids", [])
            if not ids:
                break

            for drawer_id, doc, meta in zip(
                ids, batch.get("documents", []), batch.get("metadatas", [])
            ):
                source_meta = dict(meta)
                source_meta["drawer_id"] = drawer_id
                candidates = extract_candidate_triples_from_text(
                    doc,
                    source_meta=source_meta,
                    extractor_version=extractor_version,
                )
                extracted.extend(candidates)
                if not dry_run:
                    for candidate in candidates:
                        self.propose(candidate)

            seen_drawers += len(ids)
            offset += len(ids)

        self._wal.log(
            "kg_extract",
            {
                "wing": wing,
                "room": room,
                "dry_run": dry_run,
                "drawer_count": seen_drawers,
                "candidate_count": len(extracted),
                "extractor_version": extractor_version,
            },
        )
        return extracted

    def propose(self, candidate: CandidateTriple) -> str:
        candidate_id = self._graph.propose_triple(
            subject_text=candidate.subject_text,
            predicate=candidate.predicate,
            object_text=candidate.object_text,
            confidence=candidate.confidence,
            modality=candidate.modality,
            polarity=candidate.polarity,
            valid_from=candidate.valid_from,
            valid_to=candidate.valid_to,
            evidence_drawer_id=candidate.evidence_drawer_id,
            evidence_text=candidate.evidence_text,
            source_file=candidate.source_file,
            wing=candidate.wing,
            room=candidate.room,
            extractor_version=candidate.extractor_version,
        )
        self._wal.log(
            "kg_propose",
            {
                "candidate_id": candidate_id,
                "predicate": candidate.predicate,
                "confidence": candidate.confidence,
                "evidence_drawer_id": candidate.evidence_drawer_id,
            },
        )
        return candidate_id

    def get_proposal(self, candidate_id: str) -> CandidateTriple | None:
        row = self._graph.get_candidate_triple(candidate_id=candidate_id)
        if row is None:
            return None
        return CandidateTriple(
            candidate_id=row["id"],
            subject_text=row["subject_text"],
            predicate=row["predicate"],
            object_text=row["object_text"],
            confidence=row["confidence"],
            modality=row["modality"],
            polarity=row["polarity"],
            valid_from=row.get("valid_from"),
            valid_to=row.get("valid_to"),
            evidence_drawer_id=row["evidence_drawer_id"],
            evidence_text=row["evidence_text"],
            source_file=row.get("source_file"),
            wing=row.get("wing"),
            room=row.get("room"),
            status=row["status"],
            extractor_version=row["extractor_version"],
            created_at=row.get("created_at"),
            reviewed_at=row.get("reviewed_at"),
            conflicts_with=self._find_conflicting_objects(
                subject_text=row["subject_text"],
                predicate=row["predicate"],
                object_text=row["object_text"],
                modality=row["modality"],
                polarity=row["polarity"],
            ),
        )

    def list_proposals(
        self, filter_params: CandidateTripleFilter | None = None
    ) -> list[CandidateTriple]:
        filter_params = filter_params or CandidateTripleFilter()
        rows = self._graph.list_candidate_triples(
            status=filter_params.status,
            predicate=filter_params.predicate,
            min_confidence=filter_params.min_confidence,
            wing=filter_params.wing,
            room=filter_params.room,
            limit=filter_params.limit,
            offset=filter_params.offset,
        )
        return [
            CandidateTriple(
                candidate_id=row["id"],
                subject_text=row["subject_text"],
                predicate=row["predicate"],
                object_text=row["object_text"],
                confidence=row["confidence"],
                modality=row["modality"],
                polarity=row["polarity"],
                valid_from=row.get("valid_from"),
                valid_to=row.get("valid_to"),
                evidence_drawer_id=row["evidence_drawer_id"],
                evidence_text=row["evidence_text"],
                source_file=row.get("source_file"),
                wing=row.get("wing"),
                room=row.get("room"),
                status=row["status"],
                extractor_version=row["extractor_version"],
                created_at=row.get("created_at"),
                reviewed_at=row.get("reviewed_at"),
                conflicts_with=self._find_conflicting_objects(
                    subject_text=row["subject_text"],
                    predicate=row["predicate"],
                    object_text=row["object_text"],
                    modality=row["modality"],
                    polarity=row["polarity"],
                ),
            )
            for row in rows
        ]

    def accept(self, cmd: CandidateReviewCommand) -> CandidateReviewResult:
        proposal = self.get_proposal(cmd.candidate_id)
        if proposal is None:
            return CandidateReviewResult(
                success=False,
                candidate_id=cmd.candidate_id,
                error=f"Candidate not found: {cmd.candidate_id}",
            )

        subject = cmd.subject_text or proposal.subject_text
        predicate = cmd.predicate or proposal.predicate
        obj = cmd.object_text or proposal.object_text
        valid_from = cmd.valid_from if cmd.valid_from is not None else proposal.valid_from
        valid_to = cmd.valid_to if cmd.valid_to is not None else proposal.valid_to

        invalidated_count = 0
        if cmd.action == "accept_and_invalidate_conflict":
            for conflict_object in self._find_conflicting_objects(
                subject_text=subject,
                predicate=predicate,
                object_text=obj,
                modality=proposal.modality,
                polarity=proposal.polarity,
            ):
                self._graph.invalidate(
                    subject=subject,
                    predicate=predicate,
                    obj=conflict_object,
                    ended=valid_from or date.today().isoformat(),
                )
                invalidated_count += 1

        triple_id = self._graph.add_triple(
            subject=subject,
            predicate=predicate,
            obj=obj,
            valid_from=valid_from,
            valid_to=valid_to,
            confidence=proposal.confidence,
            source_file=proposal.source_file,
        )
        reviewed_at = datetime.now().isoformat()
        self._graph.set_candidate_status(
            candidate_id=cmd.candidate_id,
            status="accepted",
            reviewed_at=reviewed_at,
        )
        self._wal.log(
            "kg_candidate_accept",
            {
                "candidate_id": cmd.candidate_id,
                "triple_id": triple_id,
                "predicate": predicate,
                "invalidated_count": invalidated_count,
            },
        )
        return CandidateReviewResult(
            success=True,
            candidate_id=cmd.candidate_id,
            status="accepted",
            triple_id=triple_id,
            invalidated_count=invalidated_count,
        )

    def reject(self, candidate_id: str) -> CandidateReviewResult:
        proposal = self.get_proposal(candidate_id)
        if proposal is None:
            return CandidateReviewResult(
                success=False,
                candidate_id=candidate_id,
                error=f"Candidate not found: {candidate_id}",
            )
        reviewed_at = datetime.now().isoformat()
        self._graph.set_candidate_status(
            candidate_id=candidate_id,
            status="rejected",
            reviewed_at=reviewed_at,
        )
        self._wal.log(
            "kg_candidate_reject",
            {
                "candidate_id": candidate_id,
                "predicate": proposal.predicate,
            },
        )
        return CandidateReviewResult(
            success=True,
            candidate_id=candidate_id,
            status="rejected",
        )
