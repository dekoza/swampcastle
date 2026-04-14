"""Tests for the KG proposal service skeleton."""

from swampcastle.models import CandidateReviewCommand, CandidateTriple
from swampcastle.services.kg_proposals import KGProposalService
from swampcastle.storage.memory import InMemoryCollectionStore, InMemoryGraphStore
from swampcastle.wal import WalWriter


def test_propose_list_accept_reject_flow(tmp_path):
    graph = InMemoryGraphStore()
    collection = InMemoryCollectionStore()
    wal = WalWriter(tmp_path / "wal")
    svc = KGProposalService(graph, collection, wal)

    candidate = CandidateTriple(
        candidate_id="cand_1",
        subject_text="SwampCastle",
        predicate="uses",
        object_text="LanceDB",
        confidence=0.91,
        modality="asserted",
        polarity="positive",
        valid_from="2026-01-01",
        evidence_drawer_id="drawer_1",
        evidence_text="SwampCastle uses LanceDB for vector storage.",
        source_file="README.md",
        wing="proj",
        room="storage",
        status="proposed",
        extractor_version="rules-v1",
    )

    proposed_id = svc.propose(candidate)
    assert proposed_id
    assert len(svc.list_proposals()) == 1

    accept_result = svc.accept(CandidateReviewCommand(candidate_id=proposed_id, action="accept"))
    assert accept_result.success is True
    assert accept_result.status == "accepted"
    assert accept_result.triple_id is not None

    kg_rows = graph.query_entity(name="SwampCastle", direction="outgoing")
    assert len(kg_rows) == 1
    assert kg_rows[0]["predicate"] == "uses"

    reject_candidate = CandidateTriple(
        candidate_id="cand_2",
        subject_text="SwampCastle",
        predicate="depends_on",
        object_text="SQLite",
        confidence=0.61,
        modality="asserted",
        polarity="positive",
        evidence_drawer_id="drawer_2",
        evidence_text="SwampCastle depends on SQLite.",
        status="proposed",
        extractor_version="rules-v1",
    )
    reject_id = svc.propose(reject_candidate)
    reject_result = svc.reject(reject_id)
    assert reject_result.success is True
    assert reject_result.status == "rejected"

    # Rejected candidate must not create a KG triple
    kg_rows = graph.query_entity(name="SwampCastle", direction="outgoing")
    predicates = {row["predicate"] for row in kg_rows}
    assert "depends_on" not in predicates


def test_list_proposals_surfaces_conflicts_for_exclusive_predicates(tmp_path):
    graph = InMemoryGraphStore()
    collection = InMemoryCollectionStore()
    wal = WalWriter(tmp_path / "wal")
    svc = KGProposalService(graph, collection, wal)

    graph.add_triple(subject="SwampCastle", predicate="uses", obj="Auth0")
    candidate_id = svc.propose(
        CandidateTriple(
            candidate_id="cand_conflict",
            subject_text="SwampCastle",
            predicate="uses",
            object_text="Clerk",
            confidence=0.95,
            modality="asserted",
            polarity="positive",
            evidence_drawer_id="drawer_1",
            evidence_text="We switched from Auth0 to Clerk.",
            status="proposed",
            extractor_version="rules-v1",
        )
    )

    proposals = svc.list_proposals()
    assert len(proposals) == 1
    assert proposals[0].candidate_id == candidate_id
    assert proposals[0].conflicts_with == ["Auth0"]


def test_accept_and_invalidate_conflict_expires_old_fact(tmp_path):
    graph = InMemoryGraphStore()
    collection = InMemoryCollectionStore()
    wal = WalWriter(tmp_path / "wal")
    svc = KGProposalService(graph, collection, wal)

    graph.add_triple(subject="SwampCastle", predicate="uses", obj="Auth0")
    candidate_id = svc.propose(
        CandidateTriple(
            candidate_id="cand_conflict",
            subject_text="SwampCastle",
            predicate="uses",
            object_text="Clerk",
            confidence=0.95,
            modality="asserted",
            polarity="positive",
            evidence_drawer_id="drawer_1",
            evidence_text="We switched from Auth0 to Clerk.",
            status="proposed",
            extractor_version="rules-v1",
        )
    )

    result = svc.accept(
        CandidateReviewCommand(
            candidate_id=candidate_id,
            action="accept_and_invalidate_conflict",
        )
    )
    assert result.success is True
    assert result.status == "accepted"
    assert result.invalidated_count == 1

    rows = graph.query_entity(name="SwampCastle", direction="outgoing")
    current = [row for row in rows if row["current"]]
    expired = [row for row in rows if not row["current"]]
    assert len(current) == 1
    assert current[0]["object"] == "Clerk"
    assert len(expired) == 1
    assert expired[0]["object"] == "Auth0"


def test_accept_with_edits_writes_edited_fact_and_reports_it(tmp_path):
    graph = InMemoryGraphStore()
    collection = InMemoryCollectionStore()
    wal = WalWriter(tmp_path / "wal")
    svc = KGProposalService(graph, collection, wal)

    candidate_id = svc.propose(
        CandidateTriple(
            candidate_id="cand_edit",
            subject_text="SwampCastle",
            predicate="uses",
            object_text="Clerk",
            confidence=0.95,
            modality="asserted",
            polarity="positive",
            evidence_drawer_id="drawer_1",
            evidence_text="We switched from Auth0 to Clerk.",
            status="proposed",
            extractor_version="rules-v1",
        )
    )

    result = svc.accept(
        CandidateReviewCommand(
            candidate_id=candidate_id,
            action="accept",
            subject_text="Auth subsystem",
            predicate="migrated_to",
            object_text="Clerk",
            valid_from="2026-02-01",
        )
    )

    assert result.success is True
    assert result.subject_text == "Auth subsystem"
    assert result.predicate == "migrated_to"
    assert result.object_text == "Clerk"

    rows = graph.query_entity(name="Auth subsystem", direction="outgoing")
    assert len(rows) == 1
    assert rows[0]["predicate"] == "migrated_to"
    assert rows[0]["object"] == "Clerk"
