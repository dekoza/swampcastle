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
