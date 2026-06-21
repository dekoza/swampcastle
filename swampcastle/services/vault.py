"""VaultService — drawer and diary write operations."""

import hashlib
import heapq
import logging
import multiprocessing
import os
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from swampcastle.models.diary import (
    DiaryEntry,
    DiaryResponse,
    DiaryWriteCommand,
    DiaryWriteResult,
)
from swampcastle.models.drawer import (
    AddDrawerCommand,
    DeleteDrawerCommand,
    DeleteDrawerResult,
    DrawerResult,
)
from swampcastle.models.record import RecordEnvelope
from swampcastle.storage.base import CollectionStore
from swampcastle.wal import WalWriter

logger = logging.getLogger("swampcastle.vault")


# ── Multiprocessing worker (must be module-level for pickling) ──────────

_worker_dialect = None


def _init_worker(cfg_path):
    global _worker_dialect
    from swampcastle.dialect import Dialect

    if cfg_path:
        _worker_dialect = Dialect.from_config(cfg_path)
    else:
        _worker_dialect = Dialect()


def _distill_worker(args):
    results = []
    for doc_id, doc, meta in args:
        meta_copy = dict(meta)
        aaak = _worker_dialect.compress(doc, metadata=meta_copy)
        meta_copy["aaak"] = aaak
        results.append((doc_id, meta_copy))
    return results


# ── DistillEngine — AAAK compression (sequential + parallel) ────────────

_DISTILL_MAX_WORKERS = 32
_DISTILL_MAX_IN_FLIGHT_BATCHES = 32
_DISTILL_TASK_BATCH_SIZE = 50
_DISTILL_WRITE_BATCH_SIZE = 500
_DISTILL_PROGRESS_UPDATE_STEP = 100

_DIARY_READ_SCAN_LIMIT = 100_000
_TOMBSTONE_ID_PREFIX = "tombstone:"


class _DistillEngine:
    """Encapsulates AAAK dialect compression logic.

    Owns the batch iteration, progress reporting, and both sequential and
    parallel execution paths.  Instantiated per-call by VaultService.distill()
    so that config_path and dialect state are not shared across invocations.
    """

    def __init__(self, collection: CollectionStore):
        self._col = collection

    # ── public entry ─────────────────────────────────────────────────

    def run(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict],
        *,
        total: int,
        dry_run: bool,
        config_path: str | None,
        max_workers: int | None,
        progress_callback: Callable[[int, int], None] | None,
        phase_progress_callback: Callable[[str, int, int], None] | None,
    ) -> int:
        self._emit(progress_callback, phase_progress_callback, "distill", 0, total)

        if max_workers is not None:
            return self._parallel(
                ids, documents, metadatas,
                total=total, dry_run=dry_run, config_path=config_path,
                max_workers=max_workers,
                progress_callback=progress_callback,
                phase_progress_callback=phase_progress_callback,
            )
        return self._sequential(
            ids, documents, metadatas,
            total=total, dry_run=dry_run, config_path=config_path,
            progress_callback=progress_callback,
            phase_progress_callback=phase_progress_callback,
        )

    # ── sequential path ───────────────────────────────────────────────

    def _sequential(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict],
        *,
        total: int,
        dry_run: bool,
        config_path: str | None,
        progress_callback: Callable[[int, int], None] | None,
        phase_progress_callback: Callable[[str, int, int], None] | None,
    ) -> int:
        from swampcastle.dialect import Dialect

        dialect = Dialect.from_config(config_path) if config_path else Dialect()

        updates = []
        processed = 0
        for doc_id, doc, meta in zip(ids, documents, metadatas):
            meta_copy = dict(meta)
            aaak = dialect.compress(doc, metadata=meta_copy)
            meta_copy["aaak"] = aaak
            updates.append((doc_id, meta_copy))
            processed += 1
            if self._should_report(processed, total):
                self._emit(progress_callback, phase_progress_callback, "distill", processed, total)

        if not dry_run and updates:
            self._flush_with_progress(updates, phase_progress_callback)
        return len(ids)

    # ── parallel path ─────────────────────────────────────────────────

    def _parallel(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict],
        *,
        total: int,
        dry_run: bool,
        config_path: str | None,
        max_workers: int,
        progress_callback: Callable[[int, int], None] | None,
        phase_progress_callback: Callable[[str, int, int], None] | None,
    ) -> int:
        task_batch_size = min(max(1, len(ids) // (max_workers * 4)), _DISTILL_TASK_BATCH_SIZE)
        in_flight_limit = min(max_workers * 4, _DISTILL_MAX_IN_FLIGHT_BATCHES)
        batch_iter = iter(self._iter_batches(ids, documents, metadatas, task_batch_size))
        write_buffer = []
        ready_results: dict[str, dict] = {}
        next_write_index = 0
        processed = 0
        spawn_context = multiprocessing.get_context("spawn")

        with ProcessPoolExecutor(
            max_workers=max_workers,
            mp_context=spawn_context,
            initializer=_init_worker,
            initargs=(config_path,),
        ) as ex:
            pending: set = set()
            for _ in range(in_flight_limit):
                batch = next(batch_iter, None)
                if batch is None:
                    break
                pending.add(ex.submit(_distill_worker, batch))

            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    batch_results = future.result()
                    processed += len(batch_results)
                    self._emit(progress_callback, phase_progress_callback, "distill", processed, total)

                    if not dry_run:
                        for doc_id, metadata in batch_results:
                            ready_results[doc_id] = metadata
                        while next_write_index < len(ids):
                            next_doc_id = ids[next_write_index]
                            if next_doc_id not in ready_results:
                                break
                            write_buffer.append((next_doc_id, ready_results.pop(next_doc_id)))
                            next_write_index += 1
                            if len(write_buffer) >= _DISTILL_WRITE_BATCH_SIZE:
                                self._flush(write_buffer)
                                write_buffer.clear()

                    batch = next(batch_iter, None)
                    if batch is not None:
                        pending.add(ex.submit(_distill_worker, batch))

        if not dry_run and write_buffer:
            self._flush_with_progress(write_buffer, phase_progress_callback)
        return processed

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _iter_batches(ids, documents, metadatas, batch_size):
        batch = []
        for item in zip(ids, documents, metadatas):
            batch.append(item)
            if len(batch) >= batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    def _flush(self, updates):
        self._col.update(
            ids=[doc_id for doc_id, _ in updates],
            metadatas=[meta for _, meta in updates],
        )

    def _flush_with_progress(self, updates, phase_cb):
        if not updates:
            return
        if phase_cb is not None:
            phase_cb("persist", 0, len(updates))
        persisted = 0
        for start in range(0, len(updates), _DISTILL_WRITE_BATCH_SIZE):
            batch = updates[start : start + _DISTILL_WRITE_BATCH_SIZE]
            self._flush(batch)
            persisted += len(batch)
            if phase_cb is not None:
                phase_cb("persist", persisted, len(updates))

    @staticmethod
    def _should_report(processed, total):
        return processed >= total or processed % _DISTILL_PROGRESS_UPDATE_STEP == 0

    @staticmethod
    def _emit(progress_cb, phase_cb, phase, processed, total):
        if phase_cb is not None:
            phase_cb(phase, processed, total)

    @staticmethod
    def resolve_workers(explicit: int | None) -> int | None:
        if explicit is not None:
            return min(explicit, _DISTILL_MAX_WORKERS) if explicit > 1 else None
        if os.environ.get("SWAMPCASTLE_DISTILL_PARALLEL", "").lower() in ("1", "true", "yes"):
            raw = os.environ.get("SWAMPCASTLE_DISTILL_WORKERS", "")
            try:
                configured = int(raw) if raw else (os.cpu_count() or 2)
            except ValueError:
                configured = os.cpu_count() or 2
            return min(configured, _DISTILL_MAX_WORKERS) if configured > 1 else None
        return None


# ── ReforgeEngine — batch re-embedding ──────────────────────────────────

_REFORGE_MIN_BATCH_SIZE = 1000
_REFORGE_MAX_PROGRESS_UPDATES = 20


class _ReforgeEngine:
    """Encapsulates batch re-embedding logic.

    Owns the offset-pagination iteration, adaptive batch sizing, and the
    sequential re-embed loop.
    """

    def __init__(self, collection: CollectionStore):
        self._col = collection

    def run(
        self,
        *,
        where: dict | None,
        total: int,
        dry_run: bool,
        batch_size: int | None,
        progress_callback: Callable[[int, int], None] | None,
    ) -> int:
        if total == 0:
            return 0
        if progress_callback is not None:
            progress_callback(0, total)
        if dry_run:
            return total

        if batch_size is not None:
            effective_bs = max(1, batch_size)
        elif progress_callback is None:
            effective_bs = total
        else:
            target = max(1, _REFORGE_MAX_PROGRESS_UPDATES)
            effective_bs = min(total, max(_REFORGE_MIN_BATCH_SIZE, (total + target - 1) // target))

        processed = 0
        for ids, docs, metas in self._iter_batches(where, effective_bs):
            self._col.upsert(ids=ids, documents=docs, metadatas=metas)
            processed += len(ids)
            if progress_callback is not None:
                progress_callback(processed, total)
        return total

    def count(self, where: dict | None) -> int:
        if not where:
            return self._col.count()
        total = 0
        offset = 0
        while True:
            batch = self._col.get(where=where, include=["ids"], limit=10_000, offset=offset)
            n = len(batch.get("ids", []))
            if n == 0:
                break
            total += n
            if n < 10_000:
                break
            offset += 10_000
        return total

    def _iter_batches(self, where, batch_size):
        offset = 0
        while True:
            results = self._col.get(
                where=where or {},
                include=["documents", "metadatas"],
                limit=batch_size,
                offset=offset,
            )
            ids = results.get("ids", [])
            if not ids:
                break
            yield ids, results.get("documents", []), results.get("metadatas", [])
            if len(ids) < batch_size:
                break
            offset += batch_size


# ── VaultService ────────────────────────────────────────────────────────


@dataclass
class GCCollectResult:
    deleted_ids: list[str]


class DiaryReadQuery(BaseModel):
    agent_name: str
    last_n: int = Field(default=10, ge=1, le=1000)


class VaultService:
    def __init__(
        self,
        collection: CollectionStore,
        wal: WalWriter,
        graph_cache_invalidator=None,
    ):
        self._col = collection
        self._wal = wal
        self._graph_cache_invalidator = graph_cache_invalidator

    def _invalidate_graph_cache(self) -> None:
        if self._graph_cache_invalidator is not None:
            self._graph_cache_invalidator()

    # ── drawer operations ─────────────────────────────────────────────

    def add_drawer(self, cmd: AddDrawerCommand) -> DrawerResult:
        drawer_id = cmd.drawer_id()

        self._wal.log(
            "add_drawer",
            {
                "drawer_id": drawer_id,
                "wing": cmd.wing,
                "room": cmd.room,
                "added_by": cmd.added_by,
                "content_length": len(cmd.content),
            },
        )

        existing = self._col.get(ids=[drawer_id])
        if existing and existing["ids"]:
            return DrawerResult(
                success=True,
                reason="already_exists",
                drawer_id=drawer_id,
            )

        self._col.upsert(
            ids=[drawer_id],
            documents=[cmd.content],
            metadatas=[
                {
                    "wing": cmd.wing,
                    "room": cmd.room,
                    "source_file": cmd.source_file or "",
                    "chunk_index": 0,
                    "added_by": cmd.added_by,
                    "filed_at": datetime.now().isoformat(),
                }
            ],
        )
        self._invalidate_graph_cache()
        return DrawerResult(
            success=True,
            drawer_id=drawer_id,
            wing=cmd.wing,
            room=cmd.room,
        )

    def add_record(self, envelope: RecordEnvelope) -> dict:
        """Store a typed canonical record.

        This is the generic typed-record write path.  Unlike
        ``add_drawer`` it does not compute a content hash-based ID —
        the caller provides ``record_id`` directly.
        """
        self._col.add_records([envelope])
        self._invalidate_graph_cache()
        return {"record_id": envelope.record_id, "kind": envelope.kind}

    def get_drawers(
        self,
        where: dict | None = None,
        include: list | None = None,
        limit: int | None = None,
        offset: int | None = None,
        *,
        ids: list[str] | None = None,
        include_tombstoned: bool = False,
    ) -> dict:
        """Retrieve drawers matching a metadata filter via the collection store.

        By default, tombstoned target records are excluded. Pass
        ``include_tombstoned=True`` to see them.
        """
        effective_include = include or ["metadatas"]
        if ids is not None:
            result = self._col.get(ids=ids, include=effective_include)
        else:
            result = self._col.get(
                where=where or {},
                include=effective_include,
                limit=limit,
                offset=offset,
            )

        if include_tombstoned or not result.get("ids"):
            return result

        active_set = self._active_tombstone_targets()
        if not active_set:
            return result

        keep_indices = [i for i, rid in enumerate(result["ids"]) if rid not in active_set]
        return {
            key: [result[key][i] for i in keep_indices]
            for key in result
            if isinstance(result[key], list)
        }

    def delete_drawer(self, cmd: DeleteDrawerCommand) -> DeleteDrawerResult:
        existing = self._col.get(ids=[cmd.drawer_id])
        if not existing["ids"]:
            return DeleteDrawerResult(
                success=False,
                drawer_id=cmd.drawer_id,
                error=f"Drawer not found: {cmd.drawer_id}",
            )

        self.create_tombstone(
            cmd.drawer_id,
            deleted_by="delete_drawer",
            reason="delete_drawer",
            grace_days=0,
        )
        self.gc_collect(
            [cmd.drawer_id],
            executed_at=datetime.now(timezone.utc),
        )
        self._invalidate_graph_cache()
        return DeleteDrawerResult(success=True, drawer_id=cmd.drawer_id)

    # ── tombstone lifecycle ───────────────────────────────────────────

    def create_tombstone(
        self,
        record_id: str,
        *,
        deleted_by: str,
        reason: str,
        grace_days: int = 90,
    ) -> str:
        """Mark a record as logically deleted."""
        now = datetime.now(timezone.utc)
        grace_until = now + timedelta(days=grace_days)
        metadata = {
            "kind": "tombstone",
            "target_record_id": record_id,
            "deleted_by": deleted_by,
            "reason": reason,
            "grace_until": grace_until.isoformat(),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        tombstone_id = f"{_TOMBSTONE_ID_PREFIX}{record_id}"
        self._col.upsert(
            documents=[record_id],
            ids=[tombstone_id],
            metadatas=[metadata],
        )
        self._wal.log(
            "create_tombstone",
            {
                "tombstone_id": tombstone_id,
                "target_record_id": record_id,
                "deleted_by": deleted_by,
                "reason": reason,
                "grace_days": grace_days,
            },
        )
        self._invalidate_graph_cache()
        return tombstone_id

    def is_tombstoned(self, record_id: str) -> bool:
        """Return True if the record has an unexpired tombstone."""
        now = datetime.now(timezone.utc)
        tombstone_id = f"{_TOMBSTONE_ID_PREFIX}{record_id}"
        result = self._col.get(ids=[tombstone_id])
        if not result["ids"]:
            return False
        metadata = result.get("metadatas", [{}])[0]
        grace_until_str = metadata.get("grace_until", "")
        if not grace_until_str:
            return True
        grace_until = datetime.fromisoformat(grace_until_str)
        return now < grace_until

    def list_pending_gc(self, *, executed_at: datetime) -> list[str]:
        """Return record IDs whose tombstones have passed their grace period."""
        raw = self._col.get(include=["metadatas"])
        targets: list[str] = []
        for rid, meta in zip(raw.get("ids", []), raw.get("metadatas", [])):
            if not rid.startswith(_TOMBSTONE_ID_PREFIX):
                continue
            target_id = meta.get("target_record_id", "")
            grace_str = meta.get("grace_until", "")
            if not target_id or not grace_str:
                continue
            try:
                grace = datetime.fromisoformat(grace_str)
            except (ValueError, TypeError):
                continue
            if executed_at >= grace:
                targets.append(target_id)
        return targets

    def gc_collect(self, record_ids: list[str], *, executed_at: datetime) -> "GCCollectResult":
        """Permanently delete records whose tombstones have expired."""
        deleted: list[str] = []
        tombstone_ids_to_delete: list[str] = []
        pending = set(self.list_pending_gc(executed_at=executed_at))
        for rid in record_ids:
            if rid not in pending:
                continue
            tombstone_ids_to_delete.append(f"{_TOMBSTONE_ID_PREFIX}{rid}")

        if tombstone_ids_to_delete:
            self._col.delete(ids=tombstone_ids_to_delete)
            self._col.delete(ids=record_ids)
            deleted = [rid for rid in record_ids if rid in pending]
            self._wal.log(
                "gc_collect",
                {"record_ids": deleted, "executed_at": executed_at.isoformat()},
            )
            self._invalidate_graph_cache()

        return GCCollectResult(deleted_ids=deleted)

    def _active_tombstone_targets(self) -> set[str]:
        """Return the set of record IDs that have unexpired tombstones."""
        now = datetime.now(timezone.utc)
        raw = self._col.get(include=["metadatas"])
        active: set[str] = set()
        for rid, meta in zip(raw.get("ids", []), raw.get("metadatas", [])):
            if not rid.startswith(_TOMBSTONE_ID_PREFIX):
                continue
            target_id = meta.get("target_record_id", "")
            grace_str = meta.get("grace_until", "")
            if not target_id or not grace_str:
                active.add(target_id)
                continue
            try:
                grace = datetime.fromisoformat(grace_str)
            except (ValueError, TypeError):
                active.add(target_id)
                continue
            if now < grace:
                active.add(target_id)
        return active

    # ── diary ─────────────────────────────────────────────────────────

    def diary_write(self, cmd: DiaryWriteCommand) -> DiaryWriteResult:
        wing = f"wing_{cmd.agent_name.lower().replace(' ', '_')}"
        now = datetime.now()
        entry_id = (
            f"diary_{wing}_{now.strftime('%Y%m%d_%H%M%S')}_"
            f"{hashlib.sha256(cmd.entry[:50].encode()).hexdigest()[:12]}"
        )

        self._wal.log(
            "diary_write",
            {"agent_name": cmd.agent_name, "topic": cmd.topic, "entry_id": entry_id},
        )

        self._col.add(
            ids=[entry_id],
            documents=[cmd.entry],
            metadatas=[
                {
                    "wing": wing,
                    "room": "diary",
                    "hall": "hall_diary",
                    "topic": cmd.topic,
                    "type": "diary_entry",
                    "agent": cmd.agent_name,
                    "filed_at": now.isoformat(),
                    "date": now.strftime("%Y-%m-%d"),
                }
            ],
        )
        self._invalidate_graph_cache()
        return DiaryWriteResult(
            success=True,
            entry_id=entry_id,
            agent=cmd.agent_name,
            topic=cmd.topic,
            timestamp=now.isoformat(),
        )

    def diary_read(self, query: DiaryReadQuery) -> DiaryResponse:
        """Return the most recent `last_n` diary entries for the agent."""
        wing = f"wing_{query.agent_name.lower().replace(' ', '_')}"

        results = self._col.get(
            where={"$and": [{"wing": wing}, {"room": "diary"}]},
            include=["documents", "metadatas"],
            limit=_DIARY_READ_SCAN_LIMIT,
        )

        if not results.get("ids"):
            return DiaryResponse(
                agent=query.agent_name,
                entries=[],
                message="No diary entries yet.",
            )

        heap: list[tuple[str, int, str, dict]] = []
        counter = 0
        for doc, meta in zip(results.get("documents", []), results.get("metadatas", [])):
            ts = meta.get("filed_at", "") or ""
            heapq.heappush(heap, (ts, counter, doc, meta))
            counter += 1
            if len(heap) > query.last_n:
                heapq.heappop(heap)

        items = sorted(heap, key=lambda x: (x[0], x[1]), reverse=True)
        entries = [
            DiaryEntry(
                date=meta.get("date", ""),
                timestamp=ts,
                topic=meta.get("topic", ""),
                content=doc,
            )
            for ts, _, doc, meta in items
        ]

        return DiaryResponse(agent=query.agent_name, entries=entries)

    # ── maintenance: distill ──────────────────────────────────────────

    def distill(
        self,
        wing: str = None,
        room: str = None,
        dry_run: bool = False,
        config_path: str = None,
        parallel_workers: int | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        phase_progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> int:
        """Compute and store AAAK Dialect summaries in drawer metadata."""
        where = {}
        if wing:
            where["wing"] = wing
        if room:
            where["room"] = room

        results = self._col.get(where=where, include=["documents", "metadatas"])
        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])
        total = len(ids)

        if not ids:
            if phase_progress_callback is not None:
                phase_progress_callback("distill", 0, 0)
            return 0

        max_workers = _DistillEngine.resolve_workers(parallel_workers)
        engine = _DistillEngine(self._col)
        return engine.run(
            ids, documents, metadatas,
            total=total, dry_run=dry_run, config_path=config_path,
            max_workers=max_workers,
            progress_callback=progress_callback,
            phase_progress_callback=phase_progress_callback,
        )

    # ── maintenance: reforge ──────────────────────────────────────────

    def reforge(
        self,
        wing: str = None,
        room: str = None,
        dry_run: bool = False,
        batch_size: int | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        """Re-embed all drawers using the currently configured embedding model."""
        where = {}
        if wing:
            where["wing"] = wing
        if room:
            where["room"] = room

        engine = _ReforgeEngine(self._col)
        total = engine.count(where or None)
        return engine.run(
            where=where or None,
            total=total,
            dry_run=dry_run,
            batch_size=batch_size,
            progress_callback=progress_callback,
        )
