"""ReforgeEngine — batch re-embedding."""

from collections.abc import Callable

from swampcastle.storage.base import CollectionStore

_REFORGE_MIN_BATCH_SIZE = 1000
_REFORGE_MAX_PROGRESS_UPDATES = 20


class ReforgeEngine:
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
