"""VaultService — drawer and diary write operations."""

import hashlib
import heapq
import logging
import multiprocessing
import os
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime

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
from swampcastle.storage.base import CollectionStore
from swampcastle.wal import WalWriter

logger = logging.getLogger("swampcastle.vault")


# Module-level variable to hold the initialized Dialect instance for the worker process
_worker_dialect = None

_DISTILL_MAX_WORKERS = 32
_DISTILL_MAX_IN_FLIGHT_BATCHES = 32
_DISTILL_TASK_BATCH_SIZE = 50
_DISTILL_WRITE_BATCH_SIZE = 500
_DISTILL_PROGRESS_UPDATE_STEP = 100


def _init_worker(cfg_path):
    global _worker_dialect
    from swampcastle.dialect import Dialect

    if cfg_path:
        _worker_dialect = Dialect.from_config(cfg_path)
    else:
        _worker_dialect = Dialect()


# Worker must be module-level so it can be pickled by multiprocessing
def _distill_worker(args):
    results = []
    for doc_id, doc, meta in args:
        meta_copy = dict(meta)
        aaak = _worker_dialect.compress(doc, metadata=meta_copy)
        meta_copy["aaak"] = aaak
        results.append((doc_id, meta_copy))
    return results


def _iter_distill_batches(
    ids: list[str],
    documents: list[str],
    metadatas: list[dict],
    batch_size: int,
):
    batch = []
    for item in zip(ids, documents, metadatas):
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _flush_distill_updates(collection: CollectionStore, updates: list[tuple[str, dict]]) -> None:
    collection.update(
        ids=[doc_id for doc_id, _ in updates],
        metadatas=[metadata for _, metadata in updates],
    )


def _should_report_distill_progress(processed: int, total: int) -> bool:
    return processed >= total or processed % _DISTILL_PROGRESS_UPDATE_STEP == 0


def _resolve_distill_workers(explicit: int | None) -> int | None:
    if explicit is not None:
        if explicit <= 1:
            return None
        return min(explicit, _DISTILL_MAX_WORKERS)
    if os.environ.get("SWAMPCASTLE_DISTILL_PARALLEL", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        raw = os.environ.get("SWAMPCASTLE_DISTILL_WORKERS", "")
        try:
            configured = int(raw) if raw else (os.cpu_count() or 2)
        except ValueError:
            configured = os.cpu_count() or 2
        if configured <= 1:
            return None
        return min(configured, _DISTILL_MAX_WORKERS)
    return None


_DIARY_READ_SCAN_LIMIT = 100_000
_REFORGE_MIN_BATCH_SIZE = 1000
_REFORGE_MAX_PROGRESS_UPDATES = 20


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

    def _distill_sequential(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict],
        *,
        total: int,
        dry_run: bool,
        config_path: str | None,
        progress_callback: Callable[[int, int], None] | None,
    ) -> int:
        from swampcastle.dialect import Dialect

        if config_path:
            dialect = Dialect.from_config(config_path)
        else:
            dialect = Dialect()

        updates = []
        processed = 0
        for doc_id, doc, meta in zip(ids, documents, metadatas):
            meta_copy = dict(meta)
            aaak = dialect.compress(doc, metadata=meta_copy)
            meta_copy["aaak"] = aaak
            updates.append((doc_id, meta_copy))
            processed += 1

            if progress_callback is not None and _should_report_distill_progress(processed, total):
                progress_callback(processed, total)

        if not dry_run and updates:
            _flush_distill_updates(self._col, updates)

        return len(ids)

    def _distill_parallel(
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
    ) -> int:
        task_batch_size = max(1, len(ids) // (max_workers * 4))
        task_batch_size = min(task_batch_size, _DISTILL_TASK_BATCH_SIZE)
        in_flight_limit = min(max_workers * 4, _DISTILL_MAX_IN_FLIGHT_BATCHES)
        batch_iter = iter(_iter_distill_batches(ids, documents, metadatas, task_batch_size))
        write_buffer = []
        ready_results = {}
        next_write_index = 0
        processed = 0
        spawn_context = multiprocessing.get_context("spawn")

        with ProcessPoolExecutor(
            max_workers=max_workers,
            mp_context=spawn_context,
            initializer=_init_worker,
            initargs=(config_path,),
        ) as ex:
            pending = set()

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

                    if progress_callback is not None:
                        progress_callback(processed, total)

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
                                _flush_distill_updates(self._col, write_buffer)
                                write_buffer.clear()

                    batch = next(batch_iter, None)
                    if batch is not None:
                        pending.add(ex.submit(_distill_worker, batch))

        if not dry_run and write_buffer:
            _flush_distill_updates(self._col, write_buffer)

        return processed

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

    def get_drawers(
        self,
        where: dict | None = None,
        include: list | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict:
        """Retrieve drawers matching a metadata filter via the collection store."""
        return self._col.get(
            where=where or {},
            include=include or ["metadatas"],
            limit=limit,
            offset=offset,
        )

    def delete_drawer(self, cmd: DeleteDrawerCommand) -> DeleteDrawerResult:
        existing = self._col.get(ids=[cmd.drawer_id])
        if not existing["ids"]:
            return DeleteDrawerResult(
                success=False,
                drawer_id=cmd.drawer_id,
                error=f"Drawer not found: {cmd.drawer_id}",
            )

        self._wal.log(
            "delete_drawer",
            {
                "drawer_id": cmd.drawer_id,
                "content_preview": existing.get("documents", [""])[0][:200],
            },
        )

        self._col.delete(ids=[cmd.drawer_id])
        self._invalidate_graph_cache()
        return DeleteDrawerResult(success=True, drawer_id=cmd.drawer_id)

    def diary_write(self, cmd: DiaryWriteCommand) -> DiaryWriteResult:
        wing = f"wing_{cmd.agent_name.lower().replace(' ', '_')}"
        now = datetime.now()
        entry_id = (
            f"diary_{wing}_{now.strftime('%Y%m%d_%H%M%S')}_"
            f"{hashlib.sha256(cmd.entry[:50].encode()).hexdigest()[:12]}"
        )

        self._wal.log(
            "diary_write",
            {
                "agent_name": cmd.agent_name,
                "topic": cmd.topic,
                "entry_id": entry_id,
            },
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
        """Return the most recent `last_n` diary entries for the agent.

        Implementation notes:
        - Backends do not expose server-side sort on `filed_at` because that
          timestamp lives in metadata, not in a dedicated indexed column.
        - Offset pagination on LanceDB is O(N²) over many pages, so we avoid
          it entirely and fetch diary rows in a single call.
        - We still keep Python-side memory bounded for the *selected* results:
          a min-heap of size `last_n` retains only the most recent entries.
        - The overall scan is capped at `_DIARY_READ_SCAN_LIMIT` rows to avoid
          unbounded reads on pathological castles.
        - We expect `filed_at` to be an ISO8601 string so lexicographic
          ordering corresponds to chronological ordering.
        """
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

        # Min-heap of (timestamp_str, counter, document, metadata)
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

    def distill(
        self,
        wing: str = None,
        room: str = None,
        dry_run: bool = False,
        config_path: str = None,
        parallel_workers: int | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        """Compute and store AAAK Dialect summaries in drawer metadata.

        AAAK Dialect is a lossy compressed symbolic format that extracts
        entities, topics, key quotes, emotions, and flags from plain text.
        These summaries are stored in the 'aaak' metadata field.

        Args:
            wing: Filter to specific wing.
            room: Filter to specific room.
            dry_run: If True, compute count but don't persist.
            config_path: Path to entities.json for custom Dialect config.
            parallel_workers: Optional worker count for CPU-bound AAAK compression.
                Values <= 1 keep the sequential path.
            progress_callback: Optional callback receiving (processed, total).

        Returns:
            Number of drawers processed.
        """
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
            if progress_callback is not None:
                progress_callback(0, 0)
            return 0

        if progress_callback is not None:
            progress_callback(0, total)

        max_workers = _resolve_distill_workers(parallel_workers)

        # Sequential fallback (preserve current behaviour by default)
        if max_workers is None:
            return self._distill_sequential(
                ids,
                documents,
                metadatas,
                total=total,
                dry_run=dry_run,
                config_path=config_path,
                progress_callback=progress_callback,
            )

        return self._distill_parallel(
            ids,
            documents,
            metadatas,
            total=total,
            dry_run=dry_run,
            config_path=config_path,
            max_workers=max_workers,
            progress_callback=progress_callback,
        )

    def reforge(
        self,
        wing: str = None,
        room: str = None,
        dry_run: bool = False,
        batch_size: int | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        """Re-embed all drawers using the currently configured embedding model.

        Useful when switching to a different model (e.g. ST -> ONNX or ONNX -> Ollama).

        Args:
            batch_size: Optional override for re-embed write batch size. If omitted,
                reforge uses a large adaptive batch size to keep progress visible
                without causing severe slowdown from many tiny upserts.
            progress_callback: Optional callback receiving (processed, total).

        Returns:
            Number of drawers processed.
        """
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
            return 0

        if progress_callback is not None:
            progress_callback(0, total)

        if dry_run:
            return total

        if batch_size is not None:
            effective_batch_size = max(1, batch_size)
        elif progress_callback is None:
            effective_batch_size = total
        else:
            target_updates = max(1, _REFORGE_MAX_PROGRESS_UPDATES)
            adaptive_batch_size = (total + target_updates - 1) // target_updates
            effective_batch_size = min(total, max(_REFORGE_MIN_BATCH_SIZE, adaptive_batch_size))

        for start in range(0, total, effective_batch_size):
            end = min(start + effective_batch_size, total)
            self._col.upsert(
                ids=ids[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )
            if progress_callback is not None:
                progress_callback(end, total)

        return total
