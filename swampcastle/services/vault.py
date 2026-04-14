"""VaultService — drawer and diary write operations."""

import hashlib
import logging
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


class DiaryReadQuery(BaseModel):
    agent_name: str
    last_n: int = Field(default=10, ge=1, le=1000)


class VaultService:
    def __init__(self, collection: CollectionStore, wal: WalWriter):
        self._col = collection
        self._wal = wal

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
        return DiaryWriteResult(
            success=True,
            entry_id=entry_id,
            agent=cmd.agent_name,
            topic=cmd.topic,
            timestamp=now.isoformat(),
        )

    def diary_read(self, query: DiaryReadQuery) -> DiaryResponse:
        wing = f"wing_{query.agent_name.lower().replace(' ', '_')}"

        results = self._col.get(
            where={"$and": [{"wing": wing}, {"room": "diary"}]},
            include=["documents", "metadatas"],
            limit=10000,
        )

        if not results["ids"]:
            return DiaryResponse(
                agent=query.agent_name,
                entries=[],
                message="No diary entries yet.",
            )

        entries = []
        for doc, meta in zip(results["documents"], results["metadatas"]):
            entries.append(
                DiaryEntry(
                    date=meta.get("date", ""),
                    timestamp=meta.get("filed_at", ""),
                    topic=meta.get("topic", ""),
                    content=doc,
                )
            )

        entries.sort(key=lambda x: x.timestamp, reverse=True)
        return DiaryResponse(
            agent=query.agent_name,
            entries=entries[: query.last_n],
        )

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

    def reforge(self, wing: str = None, room: str = None, dry_run: bool = False) -> int:
        """Re-embed all drawers using the currently configured embedding model.

        Useful when switching to a different model (e.g. ST -> ONNX or ONNX -> Ollama).

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

        if not ids:
            return 0

        if not dry_run:
            # upsert re-embeds when embeddings aren't provided
            self._col.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )

        return len(ids)
