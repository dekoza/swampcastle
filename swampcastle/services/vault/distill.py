"""DistillEngine — AAAK dialect compression (sequential + parallel)."""

import multiprocessing
import os
from collections.abc import Callable

from swampcastle.storage.base import CollectionStore

_DISTILL_MAX_WORKERS = 32
_DISTILL_MAX_IN_FLIGHT_BATCHES = 32
_DISTILL_TASK_BATCH_SIZE = 50
_DISTILL_WRITE_BATCH_SIZE = 500
_DISTILL_PROGRESS_UPDATE_STEP = 100


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


class DistillEngine:
    """Encapsulates AAAK dialect compression logic.

    Owns the batch iteration, progress reporting, and both sequential and
    parallel execution paths.  Instantiated per-call by VaultService.distill()
    so that config_path and dialect state are not shared across invocations.
    """

    def __init__(self, collection: CollectionStore):
        self._col = collection

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
        from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

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
