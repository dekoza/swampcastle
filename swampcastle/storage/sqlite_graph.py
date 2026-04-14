"""SQLite-backed knowledge graph — GraphStore implementation."""

import hashlib
import json
import sqlite3
import threading
from datetime import date, datetime
from typing import Any

from .base import GraphStore


class SQLiteGraph(GraphStore):
    """SQLite knowledge graph with temporal entity-relationship triples.

    Concurrency model:
    - one SQLite connection per thread (thread-local)
    - writes serialized by a process-local lock

    The old implementation shared one sqlite3 connection across all threads
    with check_same_thread=False, which produced InterfaceError, DatabaseError,
    and even sqlite3 SystemError under concurrent use. Per-thread connections
    avoid sqlite's connection object reentrancy hazards; the write lock keeps
    transactional writes deterministic and prevents `database is locked` races.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._connections_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._init_schema()

    def _new_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.row_factory = sqlite3.Row
        with self._connections_lock:
            self._connections.append(conn)
        return conn

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._new_conn()
            self._local.conn = conn
        return conn

    def _init_schema(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT DEFAULT 'unknown',
                properties TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS triples (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                valid_from TEXT,
                valid_to TEXT,
                confidence REAL DEFAULT 1.0,
                source_closet TEXT,
                source_file TEXT,
                extracted_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (subject) REFERENCES entities(id),
                FOREIGN KEY (object) REFERENCES entities(id)
            );

            CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject);
            CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object);
            CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate);
            CREATE INDEX IF NOT EXISTS idx_triples_valid ON triples(valid_from, valid_to);
        """)
        conn.commit()

    def _entity_id(self, name: str) -> str:
        return name.lower().replace(" ", "_").replace("'", "")

    def add_entity(self, *, name, entity_type="unknown", properties=None):
        eid = self._entity_id(name)
        props = json.dumps(properties or {})
        conn = self._get_conn()
        with self._write_lock:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO entities (id, name, type, properties) VALUES (?, ?, ?, ?)",
                    (eid, name, entity_type, props),
                )
        return eid

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
    ):
        sub_id = self._entity_id(subject)
        obj_id = self._entity_id(obj)
        pred = predicate.lower().replace(" ", "_")

        conn = self._get_conn()
        with self._write_lock:
            with conn:
                conn.execute(
                    "INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)", (sub_id, subject)
                )
                conn.execute(
                    "INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)", (obj_id, obj)
                )

                existing = conn.execute(
                    "SELECT id FROM triples WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
                    (sub_id, pred, obj_id),
                ).fetchone()
                if existing:
                    return existing["id"]

                triple_id = (
                    f"t_{sub_id}_{pred}_{obj_id}_"
                    f"{hashlib.sha256(f'{valid_from}{datetime.now().isoformat()}'.encode()).hexdigest()[:12]}"
                )
                conn.execute(
                    """INSERT INTO triples (id, subject, predicate, object, valid_from, valid_to,
                       confidence, source_closet, source_file) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        triple_id,
                        sub_id,
                        pred,
                        obj_id,
                        valid_from,
                        valid_to,
                        confidence,
                        source_closet,
                        source_file,
                    ),
                )
        return triple_id

    def invalidate(self, *, subject, predicate, obj, ended=None):
        sub_id = self._entity_id(subject)
        obj_id = self._entity_id(obj)
        pred = predicate.lower().replace(" ", "_")
        ended = ended or date.today().isoformat()
        conn = self._get_conn()
        with self._write_lock:
            with conn:
                conn.execute(
                    "UPDATE triples SET valid_to=? WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
                    (ended, sub_id, pred, obj_id),
                )

    def query_entity(self, *, name, as_of=None, direction="outgoing"):
        eid = self._entity_id(name)
        conn = self._get_conn()
        results = []

        if direction in ("outgoing", "both"):
            query = (
                "SELECT t.*, e.name as obj_name FROM triples t "
                "JOIN entities e ON t.object = e.id WHERE t.subject = ?"
            )
            params: list[Any] = [eid]
            if as_of:
                query += (
                    " AND (t.valid_from IS NULL OR t.valid_from <= ?)"
                    " AND (t.valid_to IS NULL OR t.valid_to >= ?)"
                )
                params.extend([as_of, as_of])
            for row in conn.execute(query, params).fetchall():
                results.append(
                    {
                        "direction": "outgoing",
                        "subject": name,
                        "predicate": row["predicate"],
                        "object": row["obj_name"],
                        "valid_from": row["valid_from"],
                        "valid_to": row["valid_to"],
                        "confidence": row["confidence"],
                        "source_closet": row["source_closet"],
                        "current": row["valid_to"] is None,
                    }
                )

        if direction in ("incoming", "both"):
            query = (
                "SELECT t.*, e.name as sub_name FROM triples t "
                "JOIN entities e ON t.subject = e.id WHERE t.object = ?"
            )
            params = [eid]
            if as_of:
                query += (
                    " AND (t.valid_from IS NULL OR t.valid_from <= ?)"
                    " AND (t.valid_to IS NULL OR t.valid_to >= ?)"
                )
                params.extend([as_of, as_of])
            for row in conn.execute(query, params).fetchall():
                results.append(
                    {
                        "direction": "incoming",
                        "subject": row["sub_name"],
                        "predicate": row["predicate"],
                        "object": name,
                        "valid_from": row["valid_from"],
                        "valid_to": row["valid_to"],
                        "confidence": row["confidence"],
                        "source_closet": row["source_closet"],
                        "current": row["valid_to"] is None,
                    }
                )

        return results

    def query_relationship(self, *, predicate, as_of=None):
        pred = predicate.lower().replace(" ", "_")
        conn = self._get_conn()
        query = (
            "SELECT t.*, s.name as sub_name, o.name as obj_name "
            "FROM triples t JOIN entities s ON t.subject = s.id "
            "JOIN entities o ON t.object = o.id WHERE t.predicate = ?"
        )
        params: list[Any] = [pred]
        if as_of:
            query += (
                " AND (t.valid_from IS NULL OR t.valid_from <= ?)"
                " AND (t.valid_to IS NULL OR t.valid_to >= ?)"
            )
            params.extend([as_of, as_of])
        return [
            {
                "subject": r["sub_name"],
                "predicate": pred,
                "object": r["obj_name"],
                "valid_from": r["valid_from"],
                "valid_to": r["valid_to"],
                "current": r["valid_to"] is None,
            }
            for r in conn.execute(query, params).fetchall()
        ]

    def timeline(self, *, entity_name=None):
        conn = self._get_conn()
        if entity_name:
            eid = self._entity_id(entity_name)
            rows = conn.execute(
                "SELECT t.*, s.name as sub_name, o.name as obj_name "
                "FROM triples t JOIN entities s ON t.subject = s.id "
                "JOIN entities o ON t.object = o.id "
                "WHERE (t.subject = ? OR t.object = ?) "
                "ORDER BY t.valid_from ASC NULLS LAST LIMIT 100",
                (eid, eid),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT t.*, s.name as sub_name, o.name as obj_name "
                "FROM triples t JOIN entities s ON t.subject = s.id "
                "JOIN entities o ON t.object = o.id "
                "ORDER BY t.valid_from ASC NULLS LAST LIMIT 100",
            ).fetchall()
        return [
            {
                "subject": r["sub_name"],
                "predicate": r["predicate"],
                "object": r["obj_name"],
                "valid_from": r["valid_from"],
                "valid_to": r["valid_to"],
                "current": r["valid_to"] is None,
            }
            for r in rows
        ]

    def stats(self):
        conn = self._get_conn()
        entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        triples = conn.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
        current = conn.execute("SELECT COUNT(*) FROM triples WHERE valid_to IS NULL").fetchone()[0]
        expired = triples - current
        preds = [r[0] for r in conn.execute("SELECT DISTINCT predicate FROM triples").fetchall()]
        return {
            "entities": entities,
            "triples": triples,
            "current_facts": current,
            "expired_facts": expired,
            "relationship_types": sorted(preds),
        }

    def close(self):
        with self._connections_lock:
            for conn in self._connections:
                try:
                    conn.close()
                except Exception:
                    pass
            self._connections.clear()
        self._local = threading.local()
