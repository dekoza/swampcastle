"""PostgreSQL storage backend for SwampCastle.

Collection storage uses pgvector for embeddings.
Knowledge graph storage uses plain PostgreSQL tables.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from typing import Any

from swampcastle.embeddings import get_embedder
from swampcastle.storage import StorageFactory
from swampcastle.storage.base import CollectionStore, GraphStore

try:
    import psycopg
    from pgvector import Vector
    from pgvector.psycopg import register_vector
    from psycopg_pool import ConnectionPool
except ImportError as exc:  # pragma: no cover - exercised via router/integration envs
    psycopg = None
    Vector = None
    register_vector = None
    ConnectionPool = None
    _POSTGRES_IMPORT_ERROR = exc
else:
    _POSTGRES_IMPORT_ERROR = None


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FILTER_COLUMNS = {"id", "wing", "room", "source_file", "node_id", "seq"}
_NUMERIC_FIELDS = {"seq"}


def _require_postgres_dependencies() -> None:
    if psycopg is None or ConnectionPool is None or register_vector is None or Vector is None:
        raise ImportError(
            "PostgreSQL backend requires optional dependencies. "
            "Install with: pip install 'swampcastle[postgres]'"
        ) from _POSTGRES_IMPORT_ERROR


def _validate_identifier(name: str) -> str:
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid PostgreSQL identifier: {name!r}")
    return name


def _metadata_expression(field: str, *, numeric: bool) -> tuple[str, list[Any]]:
    if field in _FILTER_COLUMNS:
        return field, []
    if numeric:
        return "CAST(metadata ->> %s AS DOUBLE PRECISION)", [field]
    return "metadata ->> %s", [field]


def _field_condition(field: str, value: Any) -> tuple[str, list[Any]]:
    if isinstance(value, dict):
        clauses = []
        params: list[Any] = []
        for op, expected in value.items():
            numeric = op in {"$gt", "$gte", "$lt", "$lte"} or field in _NUMERIC_FIELDS
            expr, expr_params = _metadata_expression(field, numeric=numeric)
            if op == "$gt":
                clauses.append(f"{expr} > %s")
                params.extend(expr_params + [expected])
            elif op == "$gte":
                clauses.append(f"{expr} >= %s")
                params.extend(expr_params + [expected])
            elif op == "$lt":
                clauses.append(f"{expr} < %s")
                params.extend(expr_params + [expected])
            elif op == "$lte":
                clauses.append(f"{expr} <= %s")
                params.extend(expr_params + [expected])
            elif op == "$ne":
                clauses.append(f"{expr} != %s")
                params.extend(expr_params + [expected])
            elif op == "$eq":
                clauses.append(f"{expr} = %s")
                params.extend(expr_params + [expected])
            elif op == "$in":
                clauses.append(f"{expr} = ANY(%s)")
                params.extend(expr_params + [list(expected)])
            elif op == "$nin":
                clauses.append(f"NOT ({expr} = ANY(%s))")
                params.extend(expr_params + [list(expected)])
            else:
                raise ValueError(f"Unsupported where operator: {op}")
        return " AND ".join(clauses), params

    numeric = isinstance(value, (int, float)) or field in _NUMERIC_FIELDS
    expr, expr_params = _metadata_expression(field, numeric=numeric)
    return f"{expr} = %s", expr_params + [value]


def _where_to_sql(where: dict[str, Any] | None) -> tuple[str, list[Any]]:
    """Convert a Chroma-style where clause into parameterized SQL."""
    if not where:
        return "", []

    if "$and" in where:
        parts = [_where_to_sql(clause) for clause in where["$and"]]
        sql = " AND ".join(f"({part})" for part, _ in parts if part)
        params: list[Any] = []
        for _, values in parts:
            params.extend(values)
        return sql, params

    if "$or" in where:
        parts = [_where_to_sql(clause) for clause in where["$or"]]
        sql = " OR ".join(f"({part})" for part, _ in parts if part)
        params = []
        for _, values in parts:
            params.extend(values)
        return sql, params

    clauses = []
    params: list[Any] = []
    for field, value in where.items():
        if field.startswith("$"):
            continue
        clause, clause_params = _field_condition(field, value)
        clauses.append(clause)
        params.extend(clause_params)
    return " AND ".join(clauses), params


def _decode_metadata(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return dict(value)


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return row[index]


class PostgresCollectionStore(CollectionStore):
    """pgvector-backed drawer storage."""

    def __init__(
        self,
        pool,
        collection_name: str,
        embedder,
        *,
        index_threshold: int = 5000,
        sync_identity=None,
    ):
        self._pool = pool
        self._table_name = _validate_identifier(collection_name)
        self._embedder = embedder
        self._index_threshold = index_threshold
        self._sync_identity = sync_identity
        self._schema_ready = False

    def _inject_sync(self, metadatas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._sync_identity is None:
            from swampcastle.sync_meta import get_identity

            self._sync_identity = get_identity()
        from swampcastle.sync_meta import inject_sync_meta

        return inject_sync_meta(metadatas, self._sync_identity)

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS _swampcastle_meta (
                        collection_name TEXT PRIMARY KEY,
                        embedding_dimension INTEGER NOT NULL,
                        embedder_model TEXT NOT NULL,
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    "SELECT embedding_dimension, embedder_model FROM _swampcastle_meta "
                    "WHERE collection_name = %s",
                    (self._table_name,),
                )
                row = cur.fetchone()
                if row is not None:
                    stored_dim = _row_value(row, "embedding_dimension", 0)
                    stored_model = _row_value(row, "embedder_model", 1)
                    if stored_dim != self._embedder.dimension:
                        raise RuntimeError(
                            "PostgreSQL collection dimension mismatch: "
                            f"table '{self._table_name}' stores {stored_dim}d vectors but "
                            f"embedder '{self._embedder.model_name}' produces "
                            f"{self._embedder.dimension}d (stored model: {stored_model})."
                        )
                else:
                    cur.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {self._table_name} (
                            id TEXT PRIMARY KEY,
                            document TEXT NOT NULL,
                            embedding vector({self._embedder.dimension}),
                            wing TEXT NOT NULL DEFAULT '',
                            room TEXT NOT NULL DEFAULT '',
                            source_file TEXT NOT NULL DEFAULT '',
                            node_id TEXT NOT NULL DEFAULT '',
                            seq BIGINT NOT NULL DEFAULT 0,
                            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                            created_at TIMESTAMPTZ DEFAULT now()
                        )
                        """
                    )
                    cur.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_{self._table_name}_wing "
                        f"ON {self._table_name} (wing)"
                    )
                    cur.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_{self._table_name}_room "
                        f"ON {self._table_name} (room)"
                    )
                    cur.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_{self._table_name}_source_file "
                        f"ON {self._table_name} (source_file)"
                    )
                    cur.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_{self._table_name}_node_seq "
                        f"ON {self._table_name} (node_id, seq)"
                    )
                    cur.execute(
                        "INSERT INTO _swampcastle_meta "
                        "(collection_name, embedding_dimension, embedder_model) "
                        "VALUES (%s, %s, %s)",
                        (self._table_name, self._embedder.dimension, self._embedder.model_name),
                    )
            conn.commit()
        self._schema_ready = True

    def _prepare_rows(
        self,
        *,
        documents: list[str],
        ids: list[str],
        metadatas: list[dict[str, Any]] | None,
        embeddings: list[list[float]] | None = None,
        raw: bool = False,
    ) -> list[tuple[Any, ...]]:
        self._ensure_schema()
        metadatas = metadatas or [{} for _ in ids]
        if not raw:
            metadatas = self._inject_sync(metadatas)
        vectors = embeddings or self._embedder.embed(documents)
        rows = []
        for doc, id_, meta, vector in zip(documents, ids, metadatas, vectors):
            metadata = dict(meta)
            metadata.setdefault("embedding_model", self._embedder.model_name)
            rows.append(
                (
                    id_,
                    doc,
                    Vector(vector) if Vector is not None else vector,
                    str(metadata.get("wing", "")),
                    str(metadata.get("room", "")),
                    str(metadata.get("source_file", "")),
                    str(metadata.get("node_id", "")),
                    int(metadata.get("seq", 0)),
                    json.dumps(metadata, default=str),
                )
            )
        return rows

    def _maybe_create_vector_index(self) -> None:
        if self._index_threshold <= 0:
            return

        index_name = f"idx_{self._table_name}_vector_hnsw"
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT count(*) FROM {self._table_name}")
                row = cur.fetchone()
                total = _row_value(row, "count", 0) if row is not None else 0
                if total < self._index_threshold:
                    return
                cur.execute(
                    "SELECT 1 FROM pg_indexes WHERE tablename = %s AND indexname = %s",
                    (self._table_name, index_name),
                )
                if cur.fetchone() is None:
                    try:
                        cur.execute(
                            f"CREATE INDEX IF NOT EXISTS {index_name} ON {self._table_name} "
                            "USING hnsw (embedding vector_cosine_ops)"
                        )
                        conn.commit()
                    except Exception as exc:
                        duplicate_index_errors = []
                        if psycopg is not None:
                            for name in ["UniqueViolation", "DuplicateObject", "DuplicateTable"]:
                                err = getattr(psycopg.errors, name, None)
                                if err is not None:
                                    duplicate_index_errors.append(err)
                        if any(isinstance(exc, err) for err in duplicate_index_errors):
                            rollback = getattr(conn, "rollback", None)
                            if rollback is not None:
                                rollback()
                            return
                        raise

    def add(self, *, documents, ids, metadatas=None) -> None:
        self.upsert(documents=documents, ids=ids, metadatas=metadatas)

    def upsert(self, *, documents, ids, metadatas=None, embeddings=None, _raw=False) -> None:
        rows = self._prepare_rows(
            documents=documents,
            ids=ids,
            metadatas=metadatas,
            embeddings=embeddings,
            raw=_raw,
        )
        if not rows:
            return

        sql = f"""
            INSERT INTO {self._table_name}
                (id, document, embedding, wing, room, source_file, node_id, seq, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (id) DO UPDATE SET
                document = EXCLUDED.document,
                embedding = EXCLUDED.embedding,
                wing = EXCLUDED.wing,
                room = EXCLUDED.room,
                source_file = EXCLUDED.source_file,
                node_id = EXCLUDED.node_id,
                seq = EXCLUDED.seq,
                metadata = EXCLUDED.metadata
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, rows)
            conn.commit()
        self._maybe_create_vector_index()

    def _row_to_result(self, row: Any) -> tuple[str, str, dict[str, Any], float | None]:
        row_id = _row_value(row, "id", 0)
        document = _row_value(row, "document", 1) or ""
        metadata = _decode_metadata(_row_value(row, "metadata", 2))
        metadata.setdefault("wing", _row_value(row, "wing", 3) or "")
        metadata.setdefault("room", _row_value(row, "room", 4) or "")
        metadata.setdefault("source_file", _row_value(row, "source_file", 5) or "")
        metadata.setdefault("node_id", _row_value(row, "node_id", 6) or "")
        metadata.setdefault("seq", _row_value(row, "seq", 7) or 0)
        distance = None
        if isinstance(row, dict) and "distance" in row:
            distance = row.get("distance")
        elif not isinstance(row, dict) and len(row) > 8:
            distance = row[8]
        return row_id, document, metadata, distance

    def get(self, *, ids=None, where=None, limit=None, offset=None, include=None) -> dict[str, Any]:
        self._ensure_schema()
        include = include or ["documents", "metadatas"]

        clauses = []
        params: list[Any] = []
        if ids is not None:
            clauses.append("id = ANY(%s)")
            params.append(list(ids))
        if where:
            where_sql, where_params = _where_to_sql(where)
            if where_sql:
                clauses.append(where_sql)
                params.extend(where_params)

        sql = (
            f"SELECT id, document, metadata, wing, room, source_file, node_id, seq "
            f"FROM {self._table_name}"
        )
        if clauses:
            sql += " WHERE " + " AND ".join(f"({clause})" for clause in clauses)
        sql += " ORDER BY id"
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)
        if offset is not None:
            sql += " OFFSET %s"
            params.append(offset)

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or None)
                rows = cur.fetchall()

        result: dict[str, Any] = {"ids": []}
        if "documents" in include:
            result["documents"] = []
        if "metadatas" in include:
            result["metadatas"] = []

        for row in rows:
            row_id, document, metadata, _ = self._row_to_result(row)
            result["ids"].append(row_id)
            if "documents" in include:
                result["documents"].append(document)
            if "metadatas" in include:
                result["metadatas"].append(metadata)
        return result

    def query(self, *, query_texts, n_results=5, where=None, include=None) -> dict[str, Any]:
        self._ensure_schema()
        include = include or ["documents", "metadatas", "distances"]
        if not query_texts:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        query_vector = (
            Vector(self._embedder.embed(query_texts[:1])[0])
            if Vector is not None
            else query_texts[0]
        )
        clauses = ["embedding IS NOT NULL"]
        params: list[Any] = [query_vector]
        if where:
            where_sql, where_params = _where_to_sql(where)
            if where_sql:
                clauses.append(where_sql)
                params.extend(where_params)

        sql = (
            f"SELECT id, document, metadata, wing, room, source_file, node_id, seq, "
            f"embedding <=> %s AS distance FROM {self._table_name}"
        )
        if clauses:
            sql += " WHERE " + " AND ".join(f"({clause})" for clause in clauses)
        sql += " ORDER BY distance LIMIT %s"
        params.append(n_results)

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

        ids_out: list[str] = []
        docs_out: list[str] = []
        metas_out: list[dict[str, Any]] = []
        dists_out: list[float] = []
        for row in rows:
            row_id, document, metadata, distance = self._row_to_result(row)
            ids_out.append(row_id)
            docs_out.append(document)
            metas_out.append(metadata)
            dists_out.append(float(distance or 0.0))
        return {
            "ids": [ids_out],
            "documents": [docs_out],
            "metadatas": [metas_out],
            "distances": [dists_out],
        }

    def delete(self, *, ids) -> None:
        self._ensure_schema()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {self._table_name} WHERE id = ANY(%s)", (list(ids),))
            conn.commit()

    def update(self, *, ids, documents=None, metadatas=None) -> None:
        if not ids:
            return
        existing = self.get(ids=ids, include=["documents", "metadatas"])
        existing_ids = set(existing["ids"])
        missing = [id_ for id_ in ids if id_ not in existing_ids]
        if missing:
            raise KeyError(f"Cannot update missing drawer IDs: {', '.join(missing)}")

        existing_map = {
            row_id: (document, metadata)
            for row_id, document, metadata in zip(
                existing["ids"], existing["documents"], existing["metadatas"]
            )
        }
        final_documents = []
        final_metadatas = []
        for index, id_ in enumerate(ids):
            current_document, current_metadata = existing_map[id_]
            final_documents.append(documents[index] if documents is not None else current_document)
            final_metadatas.append(metadatas[index] if metadatas is not None else current_metadata)
        self.upsert(documents=final_documents, ids=ids, metadatas=final_metadatas)

    def count(self) -> int:
        self._ensure_schema()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT count(*) FROM {self._table_name}")
                row = cur.fetchone()
        return int(_row_value(row, "count", 0) if row is not None else 0)

    def estimated_count(self) -> int:
        self._ensure_schema()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT reltuples::bigint FROM pg_class WHERE relname = %s", (self._table_name,)
                )
                row = cur.fetchone()
        return int(_row_value(row, "reltuples", 0) if row is not None else 0)


class PostgresGraphStore(GraphStore):
    """PostgreSQL-backed knowledge graph."""

    def __init__(self, pool):
        self._pool = pool
        self._schema_ready = False

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS kg_entities (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        type TEXT DEFAULT 'unknown',
                        properties JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS kg_triples (
                        id TEXT PRIMARY KEY,
                        subject TEXT NOT NULL REFERENCES kg_entities(id),
                        predicate TEXT NOT NULL,
                        object TEXT NOT NULL REFERENCES kg_entities(id),
                        valid_from TIMESTAMPTZ,
                        valid_to TIMESTAMPTZ,
                        confidence REAL DEFAULT 1.0,
                        source_closet TEXT,
                        source_file TEXT,
                        extracted_at TIMESTAMPTZ DEFAULT now()
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_triples_subject ON kg_triples(subject)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_triples_object ON kg_triples(object)")
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_triples_predicate ON kg_triples(predicate)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_triples_validity "
                    "ON kg_triples(valid_from, valid_to)"
                )
            conn.commit()
        self._schema_ready = True

    def _entity_id(self, name: str) -> str:
        return name.lower().replace(" ", "_").replace("'", "")

    def add_entity(self, *, name, entity_type="unknown", properties=None) -> str:
        self._ensure_schema()
        entity_id = self._entity_id(name)
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kg_entities (id, name, type, properties)
                    VALUES (%s, %s, %s, %s::jsonb)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        type = EXCLUDED.type,
                        properties = EXCLUDED.properties
                    """,
                    (entity_id, name, entity_type, json.dumps(properties or {})),
                )
            conn.commit()
        return entity_id

    def add_triple(
        self,
        *,
        subject,
        predicate,
        obj,
        valid_from=None,
        valid_to=None,
        confidence=1.0,
        source_closet=None,
        source_file=None,
    ) -> str:
        self._ensure_schema()
        subject_id = self._entity_id(subject)
        object_id = self._entity_id(obj)
        normalized_predicate = predicate.lower().replace(" ", "_")

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO kg_entities (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                    (subject_id, subject),
                )
                cur.execute(
                    "INSERT INTO kg_entities (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                    (object_id, obj),
                )
                cur.execute(
                    "SELECT id FROM kg_triples WHERE subject = %s AND predicate = %s "
                    "AND object = %s AND valid_to IS NULL",
                    (subject_id, normalized_predicate, object_id),
                )
                existing = cur.fetchone()
                if existing is not None:
                    return _row_value(existing, "id", 0)

                triple_id = (
                    f"t_{subject_id}_{normalized_predicate}_{object_id}_"
                    f"{hashlib.sha256(f'{valid_from}{datetime.now().isoformat()}'.encode()).hexdigest()[:12]}"
                )
                cur.execute(
                    """
                    INSERT INTO kg_triples (
                        id, subject, predicate, object, valid_from, valid_to,
                        confidence, source_closet, source_file
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        triple_id,
                        subject_id,
                        normalized_predicate,
                        object_id,
                        valid_from,
                        valid_to,
                        confidence,
                        source_closet,
                        source_file,
                    ),
                )
            conn.commit()
        return triple_id

    def invalidate(self, *, subject, predicate, obj, ended=None) -> None:
        self._ensure_schema()
        subject_id = self._entity_id(subject)
        object_id = self._entity_id(obj)
        normalized_predicate = predicate.lower().replace(" ", "_")
        ended = ended or date.today().isoformat()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE kg_triples SET valid_to = %s WHERE subject = %s AND predicate = %s "
                    "AND object = %s AND valid_to IS NULL",
                    (ended, subject_id, normalized_predicate, object_id),
                )
            conn.commit()

    def query_entity(self, *, name, as_of=None, direction="outgoing") -> list[dict[str, Any]]:
        self._ensure_schema()
        entity_id = self._entity_id(name)
        results: list[dict[str, Any]] = []
        validity_sql = ""
        params: list[Any]

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                if direction in ("outgoing", "both"):
                    params = [entity_id]
                    validity_sql = ""
                    if as_of:
                        validity_sql = (
                            " AND (t.valid_from IS NULL OR t.valid_from <= %s)"
                            " AND (t.valid_to IS NULL OR t.valid_to >= %s)"
                        )
                        params.extend([as_of, as_of])
                    cur.execute(
                        "SELECT t.predicate, e.name AS obj_name, t.valid_from, t.valid_to, "
                        "t.confidence, t.source_closet, t.source_file "
                        "FROM kg_triples t JOIN kg_entities e ON t.object = e.id "
                        f"WHERE t.subject = %s{validity_sql}",
                        params,
                    )
                    for row in cur.fetchall():
                        results.append(
                            {
                                "direction": "outgoing",
                                "subject": name,
                                "predicate": _row_value(row, "predicate", 0),
                                "object": _row_value(row, "obj_name", 1),
                                "valid_from": _row_value(row, "valid_from", 2),
                                "valid_to": _row_value(row, "valid_to", 3),
                                "confidence": _row_value(row, "confidence", 4),
                                "source_closet": _row_value(row, "source_closet", 5),
                                "current": _row_value(row, "valid_to", 3) is None,
                            }
                        )
                if direction in ("incoming", "both"):
                    params = [entity_id]
                    validity_sql = ""
                    if as_of:
                        validity_sql = (
                            " AND (t.valid_from IS NULL OR t.valid_from <= %s)"
                            " AND (t.valid_to IS NULL OR t.valid_to >= %s)"
                        )
                        params.extend([as_of, as_of])
                    cur.execute(
                        "SELECT t.predicate, e.name AS sub_name, t.valid_from, t.valid_to, "
                        "t.confidence, t.source_closet, t.source_file "
                        "FROM kg_triples t JOIN kg_entities e ON t.subject = e.id "
                        f"WHERE t.object = %s{validity_sql}",
                        params,
                    )
                    for row in cur.fetchall():
                        results.append(
                            {
                                "direction": "incoming",
                                "subject": _row_value(row, "sub_name", 1),
                                "predicate": _row_value(row, "predicate", 0),
                                "object": name,
                                "valid_from": _row_value(row, "valid_from", 2),
                                "valid_to": _row_value(row, "valid_to", 3),
                                "confidence": _row_value(row, "confidence", 4),
                                "source_closet": _row_value(row, "source_closet", 5),
                                "current": _row_value(row, "valid_to", 3) is None,
                            }
                        )
        return results

    def query_relationship(self, *, predicate, as_of=None) -> list[dict[str, Any]]:
        self._ensure_schema()
        normalized_predicate = predicate.lower().replace(" ", "_")
        params: list[Any] = [normalized_predicate]
        validity_sql = ""
        if as_of:
            validity_sql = (
                " AND (t.valid_from IS NULL OR t.valid_from <= %s)"
                " AND (t.valid_to IS NULL OR t.valid_to >= %s)"
            )
            params.extend([as_of, as_of])
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT s.name AS sub_name, t.predicate, o.name AS obj_name, "
                    "t.valid_from, t.valid_to FROM kg_triples t "
                    "JOIN kg_entities s ON t.subject = s.id "
                    "JOIN kg_entities o ON t.object = o.id "
                    f"WHERE t.predicate = %s{validity_sql}",
                    params,
                )
                rows = cur.fetchall()
        return [
            {
                "subject": _row_value(row, "sub_name", 0),
                "predicate": _row_value(row, "predicate", 1),
                "object": _row_value(row, "obj_name", 2),
                "valid_from": _row_value(row, "valid_from", 3),
                "valid_to": _row_value(row, "valid_to", 4),
                "current": _row_value(row, "valid_to", 4) is None,
            }
            for row in rows
        ]

    def timeline(self, *, entity_name=None) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                if entity_name:
                    entity_id = self._entity_id(entity_name)
                    cur.execute(
                        "SELECT s.name AS sub_name, t.predicate, o.name AS obj_name, "
                        "t.valid_from, t.valid_to FROM kg_triples t "
                        "JOIN kg_entities s ON t.subject = s.id "
                        "JOIN kg_entities o ON t.object = o.id "
                        "WHERE (t.subject = %s OR t.object = %s) "
                        "ORDER BY t.valid_from ASC NULLS LAST LIMIT 100",
                        (entity_id, entity_id),
                    )
                else:
                    cur.execute(
                        "SELECT s.name AS sub_name, t.predicate, o.name AS obj_name, "
                        "t.valid_from, t.valid_to FROM kg_triples t "
                        "JOIN kg_entities s ON t.subject = s.id "
                        "JOIN kg_entities o ON t.object = o.id "
                        "ORDER BY t.valid_from ASC NULLS LAST LIMIT 100"
                    )
                rows = cur.fetchall()
        return [
            {
                "subject": _row_value(row, "sub_name", 0),
                "predicate": _row_value(row, "predicate", 1),
                "object": _row_value(row, "obj_name", 2),
                "valid_from": _row_value(row, "valid_from", 3),
                "valid_to": _row_value(row, "valid_to", 4),
                "current": _row_value(row, "valid_to", 4) is None,
            }
            for row in rows
        ]

    def stats(self) -> dict[str, Any]:
        self._ensure_schema()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM kg_entities")
                entities_row = cur.fetchone()
                cur.execute("SELECT COUNT(*) FROM kg_triples")
                triples_row = cur.fetchone()
                cur.execute("SELECT COUNT(*) FROM kg_triples WHERE valid_to IS NULL")
                current_row = cur.fetchone()
                cur.execute("SELECT DISTINCT predicate FROM kg_triples")
                predicate_rows = cur.fetchall()
        entities = int(_row_value(entities_row, "count", 0) if entities_row is not None else 0)
        triples = int(_row_value(triples_row, "count", 0) if triples_row is not None else 0)
        current = int(_row_value(current_row, "count", 0) if current_row is not None else 0)
        return {
            "entities": entities,
            "triples": triples,
            "current_facts": current,
            "expired_facts": triples - current,
            "relationship_types": sorted(_row_value(row, "predicate", 0) for row in predicate_rows),
        }

    def close(self) -> None:
        return None


class PostgresStorageFactory(StorageFactory):
    """Factory for PostgreSQL-backed collections and knowledge graph stores."""

    def __init__(
        self,
        database_url: str,
        *,
        embedder=None,
        min_size: int = 2,
        max_size: int = 10,
        index_threshold: int = 5000,
    ):
        if not database_url:
            raise ValueError("database_url is required for PostgresStorageFactory")
        _require_postgres_dependencies()

        self._database_url = database_url
        self._embedder = embedder
        self._index_threshold = index_threshold
        self._graph: PostgresGraphStore | None = None

        self._pool = ConnectionPool(
            conninfo=database_url,
            min_size=min_size,
            max_size=max_size,
            open=False,
            configure=self._configure_connection,
        )
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.commit()
        self._pool.open()
        self._pool.wait()

    def _configure_connection(self, conn) -> None:
        register_vector(conn)

    def _get_embedder(self):
        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    def open_collection(self, name: str) -> PostgresCollectionStore:
        return PostgresCollectionStore(
            self._pool,
            name,
            self._get_embedder(),
            index_threshold=self._index_threshold,
        )

    def open_graph(self) -> PostgresGraphStore:
        if self._graph is None:
            self._graph = PostgresGraphStore(self._pool)
        return self._graph

    def close(self) -> None:
        self._pool.close()
