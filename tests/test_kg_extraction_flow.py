"""End-to-end proposal extraction flow tests."""

from swampcastle.models import CandidateTripleFilter
from swampcastle.services.kg_proposals import KGProposalService
from swampcastle.storage.memory import InMemoryCollectionStore, InMemoryGraphStore
from swampcastle.wal import WalWriter


def _seed_drawers(collection: InMemoryCollectionStore):
    collection.upsert(
        ids=["drawer_1", "drawer_2"],
        documents=[
            "We switched from Auth0 to Clerk because local testing got simpler.",
            "We use LanceDB for vector storage.",
        ],
        metadatas=[
            {"wing": "swampcastle", "room": "auth", "source_file": "README.md"},
            {"wing": "swampcastle", "room": "storage", "source_file": "README.md"},
        ],
    )


def test_extract_from_drawers_dry_run_returns_candidates_without_persisting(tmp_path):
    graph = InMemoryGraphStore()
    collection = InMemoryCollectionStore()
    _seed_drawers(collection)
    wal = WalWriter(tmp_path / "wal")
    svc = KGProposalService(graph, collection, wal)

    candidates = svc.extract_from_drawers(dry_run=True)

    assert len(candidates) >= 3
    assert graph.list_candidate_triples() == []
    assert graph.query_entity(name="swampcastle", direction="outgoing") == []


def test_extract_from_drawers_apply_persists_proposals_but_not_facts(tmp_path):
    graph = InMemoryGraphStore()
    collection = InMemoryCollectionStore()
    _seed_drawers(collection)
    wal = WalWriter(tmp_path / "wal")
    svc = KGProposalService(graph, collection, wal)

    candidates = svc.extract_from_drawers(dry_run=False)

    proposals = svc.list_proposals(CandidateTripleFilter(status="proposed"))
    assert len(proposals) == len(candidates)
    assert graph.query_entity(name="swampcastle", direction="outgoing") == []


def test_extract_from_drawers_is_idempotent_on_repeated_apply(tmp_path):
    graph = InMemoryGraphStore()
    collection = InMemoryCollectionStore()
    _seed_drawers(collection)
    wal = WalWriter(tmp_path / "wal")
    svc = KGProposalService(graph, collection, wal)

    first = svc.extract_from_drawers(dry_run=False)
    second = svc.extract_from_drawers(dry_run=False)

    proposals = svc.list_proposals(CandidateTripleFilter())
    assert len(proposals) == len(first)
    assert len(second) == len(first)
