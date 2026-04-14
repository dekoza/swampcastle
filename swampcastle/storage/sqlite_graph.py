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

            CREATE TABLE IF NOT EXISTS candidate_triples (
                id TEXT PRIMARY KEY,
                subject_text TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object_text TEXT NOT NULL,
                confidence REAL NOT NULL,
                modality TEXT NOT NULL,
                polarity TEXT NOT NULL,
                valid_from TEXT,
                valid_to TEXT,
                evidence_drawer_id TEXT NOT NULL,
                evidence_text TEXT NOT NULL,
                source_file TEXT,
                wing TEXT,
                room TEXT,
                status TEXT NOT NULL DEFAULT 'proposed',
                extractor_version TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_candidate_status ON candidate_triples(status);
            CREATE INDEX IF NOT EXISTS idx_candidate_predicate ON candidate_triples(predicate);
            CREATE INDEX IF NOT EXISTS idx_candidate_confidence ON candidate_triples(confidence);
            CREATE INDEX IF NOT EXISTS idx_candidate_location ON candidate_triples(wing, room);
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

    def propose_triple(
        self,
        *,
        subject_text,
        predicate,
        object_text,
        confidence,
        modality,
        polarity,
        evidence_drawer_id,
        evidence_text,
        extractor_version,
        valid_from=None,
        valid_to=None,
        source_file=None,
        wing=None,
        room=None,
    ):
        fingerprint = hashlib.sha256(
            (
                f"{subject_text}\x00{predicate}\x00{object_text}\x00{modality}\x00{polarity}\x00"
                f"{valid_from or ''}\x00{valid_to or ''}\x00{evidence_drawer_id}\x00{evidence_text}\x00"
                f"{source_file or ''}\x00{wing or ''}\x00{room or ''}"
            ).encode()
        ).hexdigest()[:16]
        candidate_id = f"cand_{fingerprint}"
        conn = self._get_conn()
        with self._write_lock:
            with conn:
                conn.execute(
                    """
                    INSERT INTO candidate_triples (
                        id, subject_text, predicate, object_text, confidence,
                        modality, polarity, valid_from, valid_to,
                        evidence_drawer_id, evidence_text, source_file,
                        wing, room, status, extractor_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?)
                    ON CONFLICT(id) DO UPDATE SET
                        subject_text = excluded.subject_text,
                        predicate = excluded.predicate,
                        object_text = excluded.object_text,
                        confidence = excluded.confidence,
                        modality = excluded.modality,
                        polarity = excluded.polarity,
                        valid_from = excluded.valid_from,
                        valid_to = excluded.valid_to,
                        evidence_drawer_id = excluded.evidence_drawer_id,
                        evidence_text = excluded.evidence_text,
                        source_file = excluded.source_file,
                        wing = excluded.wing,
                        room = excluded.room,
                        extractor_version = excluded.extractor_version
                    """,
                    (
                        candidate_id,
                        subject_text,
                        predicate,
                        object_text,
                        confidence,
                        modality,
                        polarity,
                        valid_from,
                        valid_to,
                        evidence_drawer_id,
                        evidence_text,
                        source_file,
                        wing,
                        room,
                        extractor_version,
                    ),
                )
        return candidate_id

    def get_candidate_triple(self, *, candidate_id):
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM candidate_triples WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def list_candidate_triples(
        self,
        *,
        status=None,
        predicate=None,
        min_confidence=None,
        wing=None,
        room=None,
        limit=50,
        offset=0,
    ):
        conn = self._get_conn()
        clauses = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if predicate is not None:
            clauses.append("predicate = ?")
            params.append(predicate)
        if min_confidence is not None:
            clauses.append("confidence >= ?")
            params.append(min_confidence)
        if wing is not None:
            clauses.append("wing = ?")
            params.append(wing)
        if room is not None:
            clauses.append("room = ?")
            params.append(room)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM candidate_triples {where_sql} ORDER BY created_at ASC, id ASC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return [dict(row) for row in rows]

    def set_candidate_status(self, *, candidate_id, status, reviewed_at=None):
        conn = self._get_conn()
        with self._write_lock:
            with conn:
                cur = conn.execute(
                    "UPDATE candidate_triples SET status = ?, reviewed_at = ? WHERE id = ?",
                    (status, reviewed_at, candidate_id),
                )
                return cur.rowcount > 0

    def close(self):
        with self._connections_lock:
            for conn in self._connections:
                try:
                    conn.close()
                except Exception:
                    pass
            self._connections.clear()
        self._local = threading.local()
