"""Tests for candidate triple storage in InMemoryGraphStore."""

from swampcastle.storage.memory import InMemoryGraphStore


def _propose(graph: InMemoryGraphStore) -> str:
    return graph.propose_triple(
        subject_text="SwampCastle",
        predicate="uses",
        object_text="LanceDB",
        confidence=0.9,
        modality="asserted",
        polarity="positive",
        valid_from="2026-01-01",
        valid_to=None,
        evidence_drawer_id="drawer_1",
        evidence_text="SwampCastle uses LanceDB for vector storage.",
        source_file="README.md",
        wing="proj",
        room="storage",
        extractor_version="rules-v1",
    )


def test_propose_and_get_candidate():
    graph = InMemoryGraphStore()
    candidate_id = _propose(graph)
    row = graph.get_candidate_triple(candidate_id=candidate_id)
    assert row is not None
    assert row["predicate"] == "uses"
    assert row["status"] == "proposed"


def test_list_candidate_triples_filters_by_status_and_predicate():
    graph = InMemoryGraphStore()
    candidate_id = _propose(graph)
    graph.set_candidate_status(
        candidate_id=candidate_id, status="accepted", reviewed_at="2026-01-02T00:00:00"
    )

    proposed = graph.list_candidate_triples(status="proposed")
    accepted = graph.list_candidate_triples(status="accepted", predicate="uses")

    assert proposed == []
    assert len(accepted) == 1
    assert accepted[0]["id"] == candidate_id


def test_list_candidate_triples_respects_limit_offset():
    graph = InMemoryGraphStore()
    ids = [_propose(graph) for _ in range(3)]

    first = graph.list_candidate_triples(limit=2, offset=0)
    second = graph.list_candidate_triples(limit=2, offset=2)

    assert len(first) == 2
    assert len(second) == 1
    assert {row["id"] for row in first + second} == set(ids)
