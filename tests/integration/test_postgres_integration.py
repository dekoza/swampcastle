"""Integration tests for the PostgreSQL storage backend."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from swampcastle.storage.postgres import PostgresStorageFactory


class FakeEmbedder3D:
    model_name = "fake-3d"
    dimension = 3

    def embed(self, texts):
        vectors = []
        for text in texts:
            lower = text.lower()
            if "auth" in lower:
                vectors.append([1.0, 0.0, 0.0])
            elif "billing" in lower:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


class FakeEmbedder4D:
    model_name = "fake-4d"
    dimension = 4

    def embed(self, texts):
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


@pytest.fixture(scope="module")
def database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set; run integration tests via compose.test.yml")
    return url


@pytest.fixture
def factory(database_url):
    backend = PostgresStorageFactory(
        database_url,
        embedder=FakeEmbedder3D(),
        min_size=1,
        max_size=4,
        index_threshold=2,
    )
    try:
        yield backend
    finally:
        backend.close()


def _unique_collection_name() -> str:
    return f"swampcastle_test_{uuid4().hex[:12]}"


def _drop_collection(database_url: str, collection_name: str) -> None:
    import psycopg

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {collection_name}")
            cur.execute(
                "DELETE FROM _swampcastle_meta WHERE collection_name = %s",
                (collection_name,),
            )
        conn.commit()


def _reset_graph(database_url: str) -> None:
    import psycopg

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM kg_triples")
            cur.execute("DELETE FROM kg_entities")
        conn.commit()


@pytest.mark.integration
@pytest.mark.postgres
def test_collection_crud_round_trip(factory, database_url):
    collection_name = _unique_collection_name()
    try:
        collection = factory.open_collection(collection_name)
        collection.add(
            documents=["auth token rotation"],
            ids=["d1"],
            metadatas=[{"wing": "proj", "room": "auth", "source_file": "auth.py"}],
        )

        created = collection.get(ids=["d1"], include=["documents", "metadatas"])
        assert created["documents"] == ["auth token rotation"]
        assert created["metadatas"][0]["room"] == "auth"

        collection.update(ids=["d1"], documents=["auth token rotation v2"])
        updated = collection.get(ids=["d1"], include=["documents"])
        assert updated["documents"] == ["auth token rotation v2"]

        collection.delete(ids=["d1"])
        deleted = collection.get(ids=["d1"], include=["documents"])
        assert deleted["ids"] == []
    finally:
        _drop_collection(database_url, collection_name)


@pytest.mark.integration
@pytest.mark.postgres
def test_vector_search_and_where_filters(factory, database_url):
    collection_name = _unique_collection_name()
    try:
        collection = factory.open_collection(collection_name)
        collection.upsert(
            documents=[
                "auth tokens and refresh rotation",
                "billing retries and invoice handling",
                "general architecture notes",
            ],
            ids=["auth-1", "billing-1", "general-1"],
            metadatas=[
                {"wing": "proj", "room": "auth", "source_file": "auth.py"},
                {"wing": "proj", "room": "billing", "source_file": "billing.py"},
                {"wing": "notes", "room": "general", "source_file": "notes.md"},
            ],
        )

        result = collection.query(
            query_texts=["auth rotation"],
            n_results=2,
            include=["documents", "metadatas", "distances"],
        )
        assert result["ids"][0][0] == "auth-1"

        filtered = collection.query(
            query_texts=["billing retries"],
            n_results=2,
            where={"wing": "proj", "room": "billing"},
            include=["documents", "metadatas", "distances"],
        )
        assert filtered["ids"][0] == ["billing-1"]
    finally:
        _drop_collection(database_url, collection_name)


@pytest.mark.integration
@pytest.mark.postgres
def test_upsert_idempotent_and_estimated_count(factory, database_url):
    import psycopg

    collection_name = _unique_collection_name()
    try:
        collection = factory.open_collection(collection_name)
        collection.upsert(
            documents=["auth policy"],
            ids=["same-id"],
            metadatas=[{"wing": "proj", "room": "auth", "source_file": "a.py"}],
        )
        collection.upsert(
            documents=["auth policy updated"],
            ids=["same-id"],
            metadatas=[{"wing": "proj", "room": "auth", "source_file": "a.py"}],
        )

        assert collection.count() == 1

        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(f"ANALYZE {collection_name}")
            conn.commit()

        assert collection.estimated_count() >= 1
    finally:
        _drop_collection(database_url, collection_name)


@pytest.mark.integration
@pytest.mark.postgres
def test_dimension_mismatch_is_rejected(database_url):
    collection_name = _unique_collection_name()
    factory_3d = PostgresStorageFactory(database_url, embedder=FakeEmbedder3D(), min_size=1, max_size=2)
    try:
        collection = factory_3d.open_collection(collection_name)
        collection.upsert(
            documents=["auth policy"],
            ids=["d1"],
            metadatas=[{"wing": "proj", "room": "auth", "source_file": "a.py"}],
        )
    finally:
        factory_3d.close()

    factory_4d = PostgresStorageFactory(database_url, embedder=FakeEmbedder4D(), min_size=1, max_size=2)
    try:
        with pytest.raises(RuntimeError, match="dimension mismatch"):
            factory_4d.open_collection(collection_name).count()
    finally:
        factory_4d.close()
        _drop_collection(database_url, collection_name)


@pytest.mark.integration
@pytest.mark.postgres
def test_hnsw_index_created_after_threshold(factory, database_url):
    import psycopg

    collection_name = _unique_collection_name()
    try:
        collection = factory.open_collection(collection_name)
        collection.upsert(
            documents=["auth one", "auth two"],
            ids=["d1", "d2"],
            metadatas=[
                {"wing": "proj", "room": "auth", "source_file": "a.py"},
                {"wing": "proj", "room": "auth", "source_file": "b.py"},
            ],
        )

        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT indexname FROM pg_indexes WHERE tablename = %s AND indexname = %s",
                    (collection_name, f"idx_{collection_name}_vector_hnsw"),
                )
                row = cur.fetchone()
        assert row is not None
    finally:
        _drop_collection(database_url, collection_name)


@pytest.mark.integration
@pytest.mark.postgres
def test_graph_crud_and_temporal_queries(factory, database_url):
    graph = factory.open_graph()
    graph.stats()
    _reset_graph(database_url)
    try:
        triple_id = graph.add_triple(
            subject="Kai",
            predicate="works_on",
            obj="Orion",
            valid_from="2025-01-01T00:00:00+00:00",
        )
        assert triple_id

        active = graph.query_entity(name="Kai", as_of="2025-06-15T00:00:00+00:00")
        assert len(active) == 1
        assert active[0]["object"] == "Orion"

        graph.invalidate(
            subject="Kai",
            predicate="works_on",
            obj="Orion",
            ended="2025-12-31T00:00:00+00:00",
        )
        graph.add_triple(
            subject="Kai",
            predicate="works_on",
            obj="Nova",
            valid_from="2026-01-01T00:00:00+00:00",
        )

        future = graph.query_entity(name="Kai", as_of="2026-06-15T00:00:00+00:00")
        assert len(future) == 1
        assert future[0]["object"] == "Nova"

        timeline = graph.timeline(entity_name="Kai")
        assert len(timeline) == 2
        stats = graph.stats()
        assert stats["entities"] >= 3
        assert stats["triples"] == 2
        assert "works_on" in stats["relationship_types"]
    finally:
        _reset_graph(database_url)


@pytest.mark.integration
@pytest.mark.postgres
def test_pool_supports_concurrent_collection_operations(factory, database_url):
    collection_name = _unique_collection_name()
    try:
        collection = factory.open_collection(collection_name)
        collection.count()  # ensure schema exists before concurrent upserts

        def insert_one(index: int) -> None:
            collection.upsert(
                documents=[f"auth doc {index}"],
                ids=[f"d{index}"],
                metadatas=[{"wing": "proj", "room": "auth", "source_file": f"{index}.py"}],
            )

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(insert_one, range(8)))

        assert collection.count() == 8
    finally:
        _drop_collection(database_url, collection_name)
