"""VaultService — drawer and diary write operations."""

import hashlib
import heapq
import logging
from collections.abc import Callable
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

        Returns:
            Number of drawers processed.
        """
        from swampcastle.dialect import Dialect

        if config_path:
            dialect = Dialect.from_config(config_path)
        else:
            dialect = Dialect()
        where = {}
        if wing:
            where["wing"] = wing
        if room:
            where["room"] = room

        results = self._col.get(where=where, include=["documents", "metadatas"])
        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])

        if not ids:
            return 0

        updates = []
        for doc_id, doc, meta in zip(ids, documents, metadatas):
            # Copy metadata before mutating to avoid side effects
            meta_copy = dict(meta)
            aaak = dialect.compress(doc, metadata=meta_copy)
            meta_copy["aaak"] = aaak
            updates.append(
                {
                    "id": doc_id,
                    "metadata": meta_copy,
                }
            )

        if not dry_run:
            # use update() which backends must implement
            self._col.update(
                ids=[u["id"] for u in updates],
                metadatas=[u["metadata"] for u in updates],
            )

        return len(ids)

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
