"""VaultService — drawer and diary write operations."""

import hashlib
import heapq
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

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
from swampcastle.services.vault.distill import DistillEngine
from swampcastle.services.vault.models import DiaryReadQuery, GCCollectResult
from swampcastle.services.vault.reforge import ReforgeEngine
from swampcastle.storage.base import CollectionStore
from swampcastle.wal import WalWriter

logger = logging.getLogger("swampcastle.vault")

_DIARY_READ_SCAN_LIMIT = 100_000
_TOMBSTONE_ID_PREFIX = "tombstone:"


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
        self._tombstone_targets: set[str] = set()
        self._load_tombstones()

    def _load_tombstones(self) -> None:
        """Load existing tombstones from collection into memory."""
        try:
            raw = self._col.get(include=["metadatas"])
        except Exception:
            return
        for rid, meta in zip(raw.get("ids", []), raw.get("metadatas", [])):
            if rid.startswith(_TOMBSTONE_ID_PREFIX):
                target_id = meta.get("target_record_id", "")
                if target_id:
                    self._tombstone_targets.add(target_id)

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

        if not self._tombstone_targets:
            return result

        keep_indices = [i for i, rid in enumerate(result["ids"]) if rid not in self._tombstone_targets]
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
        self._tombstone_targets.add(record_id)
        self._invalidate_graph_cache()
        return tombstone_id

    def is_tombstoned(self, record_id: str) -> bool:
        """Return True if the record has an unexpired tombstone."""
        return record_id in self._tombstone_targets

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

    def gc_collect(self, record_ids: list[str], *, executed_at: datetime) -> GCCollectResult:
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
            self._tombstone_targets.difference_update(deleted)
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

        max_workers = DistillEngine.resolve_workers(parallel_workers)
        engine = DistillEngine(self._col)
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

        engine = ReforgeEngine(self._col)
        total = engine.count(where or None)
        return engine.run(
            where=where or None,
            total=total,
            dry_run=dry_run,
            batch_size=batch_size,
            progress_callback=progress_callback,
        )
