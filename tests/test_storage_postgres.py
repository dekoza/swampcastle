"""Unit tests for the PostgreSQL storage backend."""

from contextlib import contextmanager

import pytest

from swampcastle.storage import StorageFactory
from swampcastle.storage.base import CollectionStore, GraphStore
from swampcastle.storage.postgres import (
    PostgresCollectionStore,
    PostgresGraphStore,
    PostgresStorageFactory,
    _where_to_sql,
)


class FakeEmbedder:
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


class RecordingCursor:
    def __init__(self, conn):
        self._conn = conn
        self.rowcount = conn.rowcount

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def execute(self, sql, params=None):
        self._conn.executed.append(("execute", sql, params))
        self.rowcount = self._conn.rowcount
        return self

    def executemany(self, sql, params_seq):
        rows = list(params_seq)
        self._conn.executed.append(("executemany", sql, rows))
        self.rowcount = len(rows)
        return self

    def fetchone(self):
        if self._conn.fetchone_queue:
            return self._conn.fetchone_queue.pop(0)
        return None

    def fetchall(self):
        if self._conn.fetchall_queue:
            return self._conn.fetchall_queue.pop(0)
        return []


class RecordingConnection:
    def __init__(self, *, fetchone=None, fetchall=None, rowcount=0):
        self.executed = []
        self.fetchone_queue = list(fetchone or [])
        self.fetchall_queue = list(fetchall or [])
        self.rowcount = rowcount
        self.commits = 0

    def cursor(self):
        return RecordingCursor(self)

    def commit(self):
        self.commits += 1


class RecordingPool:
    def __init__(self, conn=None, **kwargs):
        self.conn = conn or RecordingConnection()
        self.kwargs = kwargs
        self.closed = False
        self.opened = False
        self.waited = False

    @contextmanager
    def connection(self):
        yield self.conn

    def open(self):
        self.opened = True

    def wait(self):
        self.waited = True

    def close(self):
        self.closed = True


class TestWhereToSql:
    def test_nested_filters_are_parameterized(self):
        sql, params = _where_to_sql(
            {
                "$and": [
                    {"wing": "proj"},
                    {"$or": [{"room": "auth"}, {"seq": {"$gte": 2}}]},
                    {"source_file": {"$ne": ""}},
                ]
            }
        )
        assert sql == "(wing = %s) AND ((room = %s) OR (seq >= %s)) AND (source_file != %s)"
        assert params == ["proj", "auth", 2, ""]

    def test_in_and_nin_filters(self):
        sql, params = _where_to_sql(
            {"$and": [{"wing": {"$in": ["proj", "infra"]}}, {"room": {"$nin": ["tmp"]}}]}
        )
        assert sql == "(wing = ANY(%s)) AND (NOT (room = ANY(%s)))"
        assert params == [["proj", "infra"], ["tmp"]]


class TestPostgresCollectionStore:
    def test_is_collection_store(self):
        store = PostgresCollectionStore(RecordingPool(), "swampcastle_chests", FakeEmbedder())
        assert isinstance(store, CollectionStore)

    def test_init_creates_meta_and_collection_tables(self):
        conn = RecordingConnection(fetchone=[None])
        store = PostgresCollectionStore(RecordingPool(conn), "swampcastle_chests", FakeEmbedder())

        store._ensure_schema()

        ddl = "\n".join(sql for _, sql, _ in conn.executed)
        assert "CREATE TABLE IF NOT EXISTS _swampcastle_meta" in ddl
        assert "CREATE TABLE IF NOT EXISTS swampcastle_chests" in ddl
        assert "vector(3)" in ddl
        assert "INSERT INTO _swampcastle_meta" in ddl
        assert conn.commits >= 1

    def test_init_rejects_dimension_mismatch(self):
        conn = RecordingConnection(fetchone=[(768, "other-model")])
        store = PostgresCollectionStore(RecordingPool(conn), "swampcastle_chests", FakeEmbedder())

        with pytest.raises(RuntimeError, match="dimension mismatch"):
            store._ensure_schema()

    def test_upsert_uses_batch_insert(self):
        conn = RecordingConnection(fetchone=[None, (0,), None])
        store = PostgresCollectionStore(
            RecordingPool(conn), "swampcastle_chests", FakeEmbedder(), index_threshold=5
        )

        store.upsert(
            documents=["auth policy", "billing policy"],
            ids=["d1", "d2"],
            metadatas=[
                {"wing": "proj", "room": "auth", "source_file": "a.py"},
                {"wing": "proj", "room": "billing", "source_file": "b.py"},
            ],
        )

        kind, sql, rows = next(item for item in conn.executed if item[0] == "executemany")
        assert kind == "executemany"
        assert "ON CONFLICT (id) DO UPDATE" in sql
        assert len(rows) == 2
        assert rows[0][0] == "d1"
        assert rows[0][3] == "proj"

    def test_update_raises_when_id_missing(self):
        conn = RecordingConnection(fetchone=[None], rowcount=0)
        store = PostgresCollectionStore(RecordingPool(conn), "swampcastle_chests", FakeEmbedder())

        with pytest.raises(KeyError, match="missing"):
            store.update(ids=["missing"], documents=["new text"])

    def test_creates_hnsw_index_after_threshold(self):
        conn = RecordingConnection(fetchone=[None, (6,), None])
        store = PostgresCollectionStore(
            RecordingPool(conn), "swampcastle_chests", FakeEmbedder(), index_threshold=5
        )

        store.upsert(
            documents=["auth policy"],
            ids=["d1"],
            metadatas=[{"wing": "proj", "room": "auth", "source_file": "a.py"}],
        )

        ddl = "\n".join(sql for _, sql, _ in conn.executed)
        assert "CREATE INDEX IF NOT EXISTS idx_swampcastle_chests_vector_hnsw" in ddl


class TestPostgresGraphStore:
    def test_is_graph_store(self):
        store = PostgresGraphStore(RecordingPool())
        assert isinstance(store, GraphStore)

    def test_add_entity_upserts(self):
        conn = RecordingConnection()
        store = PostgresGraphStore(RecordingPool(conn))

        entity_id = store.add_entity(name="Kai", entity_type="person", properties={"role": "dev"})

        assert entity_id == "kai"
        sql = conn.executed[-1][1]
        assert "INSERT INTO kg_entities" in sql
        assert "ON CONFLICT (id) DO UPDATE" in sql

    def test_add_triple_returns_existing_active_duplicate(self):
        conn = RecordingConnection(fetchone=[{"id": "existing-triple"}])
        store = PostgresGraphStore(RecordingPool(conn))

        triple_id = store.add_triple(subject="Kai", predicate="works_on", obj="Orion")

        assert triple_id == "existing-triple"

    def test_query_entity_maps_rows(self):
        row = {
            "predicate": "works_on",
            "obj_name": "Orion",
            "valid_from": "2025-01-01",
            "valid_to": None,
            "confidence": 1.0,
            "source_closet": None,
        }
        conn = RecordingConnection(fetchall=[[row]])
        store = PostgresGraphStore(RecordingPool(conn))

        results = store.query_entity(name="Kai")

        assert results == [
            {
                "direction": "outgoing",
                "subject": "Kai",
                "predicate": "works_on",
                "object": "Orion",
                "valid_from": "2025-01-01",
                "valid_to": None,
                "confidence": 1.0,
                "source_closet": None,
                "current": True,
            }
        ]


class TestPostgresStorageFactory:
    def test_is_storage_factory(self, monkeypatch):
        fake_pool = RecordingPool()
        raw_conn = RecordingConnection()

        def fake_connection_pool(**kwargs):
            fake_pool.kwargs = kwargs
            return fake_pool

        @contextmanager
        def fake_connect(dsn):
            assert dsn == "postgresql://localhost/swampcastle"
            yield raw_conn

        monkeypatch.setattr("swampcastle.storage.postgres.ConnectionPool", fake_connection_pool)
        monkeypatch.setattr("swampcastle.storage.postgres.register_vector", lambda conn: None)
        monkeypatch.setattr("swampcastle.storage.postgres.Vector", lambda value: value)
        monkeypatch.setattr(
            "swampcastle.storage.postgres.psycopg",
            type("P", (), {"connect": staticmethod(fake_connect)}),
        )

        factory = PostgresStorageFactory(
            "postgresql://localhost/swampcastle", embedder=FakeEmbedder()
        )

        assert isinstance(factory, StorageFactory)
        assert factory._pool is fake_pool
        assert fake_pool.kwargs["conninfo"] == "postgresql://localhost/swampcastle"
        assert fake_pool.kwargs["open"] is False
        assert fake_pool.opened is True
        assert fake_pool.waited is True
        assert raw_conn.executed[0][1] == "CREATE EXTENSION IF NOT EXISTS vector"

    def test_requires_database_url(self):
        with pytest.raises(ValueError, match="database_url"):
            PostgresStorageFactory("")

    def test_open_collection_and_graph(self, monkeypatch):
        fake_pool = RecordingPool()

        @contextmanager
        def fake_connect(dsn):
            yield RecordingConnection()

        monkeypatch.setattr(
            "swampcastle.storage.postgres.ConnectionPool", lambda **kwargs: fake_pool
        )
        monkeypatch.setattr("swampcastle.storage.postgres.register_vector", lambda conn: None)
        monkeypatch.setattr("swampcastle.storage.postgres.Vector", lambda value: value)
        monkeypatch.setattr(
            "swampcastle.storage.postgres.psycopg",
            type("P", (), {"connect": staticmethod(fake_connect)}),
        )

        factory = PostgresStorageFactory(
            "postgresql://localhost/swampcastle", embedder=FakeEmbedder()
        )

        collection = factory.open_collection("swampcastle_chests")
        graph = factory.open_graph()

        assert isinstance(collection, PostgresCollectionStore)
        assert isinstance(graph, PostgresGraphStore)

    def test_close_shuts_pool(self, monkeypatch):
        fake_pool = RecordingPool()

        @contextmanager
        def fake_connect(dsn):
            yield RecordingConnection()

        monkeypatch.setattr(
            "swampcastle.storage.postgres.ConnectionPool", lambda **kwargs: fake_pool
        )
        monkeypatch.setattr("swampcastle.storage.postgres.register_vector", lambda conn: None)
        monkeypatch.setattr("swampcastle.storage.postgres.Vector", lambda value: value)
        monkeypatch.setattr(
            "swampcastle.storage.postgres.psycopg",
            type("P", (), {"connect": staticmethod(fake_connect)}),
        )

        factory = PostgresStorageFactory(
            "postgresql://localhost/swampcastle", embedder=FakeEmbedder()
        )
        factory.close()

        assert fake_pool.closed is True
