"""Tests for candidate triple storage in SQLiteGraph."""

from swampcastle.storage.sqlite_graph import SQLiteGraph


def _propose(graph: SQLiteGraph) -> str:
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


def test_sqlite_candidate_propose_get_list(tmp_path):
    graph = SQLiteGraph(str(tmp_path / "kg.sqlite3"))
    try:
        candidate_id = _propose(graph)
        row = graph.get_candidate_triple(candidate_id=candidate_id)
        assert row is not None
        assert row["id"] == candidate_id
        assert row["status"] == "proposed"

        listed = graph.list_candidate_triples(status="proposed")
        assert len(listed) == 1
        assert listed[0]["id"] == candidate_id
    finally:
        graph.close()


def test_sqlite_candidate_status_transition(tmp_path):
    graph = SQLiteGraph(str(tmp_path / "kg.sqlite3"))
    try:
        candidate_id = _propose(graph)
        updated = graph.set_candidate_status(
            candidate_id=candidate_id,
            status="accepted",
            reviewed_at="2026-01-02T00:00:00",
        )
        assert updated is True
        row = graph.get_candidate_triple(candidate_id=candidate_id)
        assert row["status"] == "accepted"
        assert row["reviewed_at"] is not None
    finally:
        graph.close()
