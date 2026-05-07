"""Tests for rebuildable derived audit artifacts."""

from __future__ import annotations

import json

from swampcastle.audit.derived import (
    load_catalog_cards,
    load_search_trace,
    rebuild_catalog,
    write_search_trace,
)
from swampcastle.models import SearchHit, SearchQuery, SearchResponse
from swampcastle.storage.memory import InMemoryCollectionStore


def _add_doc(collection, doc_id: str, text: str, *, wing: str, room: str, source_file: str):
    collection.upsert(
        documents=[text],
        ids=[doc_id],
        metadatas=[{"wing": wing, "room": room, "source_file": source_file}],
    )


def test_rebuild_catalog_is_idempotent(tmp_path):
    collection = InMemoryCollectionStore()
    _add_doc(
        collection,
        "d1",
        "Auth migration moved from Auth0 to Clerk and simplified local testing.",
        wing="swampcastle",
        room="auth",
        source_file="/tmp/auth.md",
    )
    _add_doc(
        collection,
        "d2",
        "Clerk rollout notes with auth migration follow-up tasks.",
        wing="swampcastle",
        room="auth",
        source_file="/tmp/auth.md",
    )

    first = rebuild_catalog(collection, tmp_path / "castle")
    first_payload = (
        tmp_path / "castle" / ".swampcastle" / "derived" / "catalog" / "swampcastle.jsonl"
    ).read_text(encoding="utf-8")

    second = rebuild_catalog(collection, tmp_path / "castle")
    second_payload = (
        tmp_path / "castle" / ".swampcastle" / "derived" / "catalog" / "swampcastle.jsonl"
    ).read_text(encoding="utf-8")

    assert first == second
    assert first_payload == second_payload


def test_rebuild_catalog_is_stable_under_drawer_reorder(tmp_path):
    left = InMemoryCollectionStore()
    right = InMemoryCollectionStore()
    records = [
        ("d1", "Auth migration moved from Auth0 to Clerk.", "swampcastle", "auth", "/tmp/auth.md"),
        ("d2", "Clerk follow-up notes for auth rollout.", "swampcastle", "auth", "/tmp/auth.md"),
        (
            "d3",
            "Sync protocol notes for laptop replication.",
            "swampcastle",
            "sync",
            "/tmp/sync.md",
        ),
    ]

    for doc_id, text, wing, room, source_file in records:
        _add_doc(left, doc_id, text, wing=wing, room=room, source_file=source_file)
    for doc_id, text, wing, room, source_file in reversed(records):
        _add_doc(right, doc_id, text, wing=wing, room=room, source_file=source_file)

    rebuild_catalog(left, tmp_path / "left")
    rebuild_catalog(right, tmp_path / "right")

    left_cards = [
        card.model_dump() for card in load_catalog_cards(tmp_path / "left", "swampcastle")
    ]
    right_cards = [
        card.model_dump() for card in load_catalog_cards(tmp_path / "right", "swampcastle")
    ]

    assert left_cards == right_cards


def test_rebuild_catalog_removes_stale_wing_files_on_full_rebuild(tmp_path):
    collection = InMemoryCollectionStore()
    _add_doc(
        collection,
        "d1",
        "Auth migration moved from Auth0 to Clerk.",
        wing="swampcastle",
        room="auth",
        source_file="/tmp/auth.md",
    )

    catalog_dir = tmp_path / "castle" / ".swampcastle" / "derived" / "catalog"
    catalog_dir.mkdir(parents=True)
    (catalog_dir / "oldwing.jsonl").write_text(
        json.dumps(
            {
                "wing": "oldwing",
                "room": "old",
                "topic": "stale",
                "entities": [],
                "drawer_ids": [],
                "source_files": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    rebuild_catalog(collection, tmp_path / "castle")

    assert not (catalog_dir / "oldwing.jsonl").exists()
    assert (catalog_dir / "swampcastle.jsonl").exists()


def test_write_search_trace_round_trip(tmp_path):
    query = SearchQuery(query="auth migration clerk", limit=2, hybrid=True, explain=True)
    response = SearchResponse(
        query="auth migration clerk",
        results=[
            SearchHit(
                text="Auth migration moved from Auth0 to Clerk.",
                wing="swampcastle",
                room="auth",
                similarity=0.92,
                matched_via="hybrid",
                dense_similarity=0.89,
                lexical_score=1.0,
                boosts=["hybrid_candidate_merge", "lexical_rerank"],
                origin_id="origin_123",
                source_kind="conversation_export",
                source_platform="claude-code",
            )
        ],
        filters={"wing": None, "room": None, "contributor": None},
        query_sanitized=False,
        sanitizer=None,
    )

    path = write_search_trace(tmp_path / "castle", query, response)
    loaded = load_search_trace(path)

    assert loaded.request.query == "auth migration clerk"
    assert loaded.request.hybrid is True
    assert loaded.response.results[0].matched_via == "hybrid"
    assert loaded.response.results[0].origin_id == "origin_123"
