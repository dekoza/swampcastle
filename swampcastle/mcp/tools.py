"""MCP tool registry — Pydantic models as schema source of truth."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel, Field

from swampcastle.castle import Castle
from swampcastle.models.audit import (
    CatalogCardsQuery,
    CurationQuery,
    OriginLookupQuery,
)
from swampcastle.models.catalog import StatusInput
from swampcastle.models.checkpoint import CheckpointCommand, CheckpointResult
from swampcastle.models.diary import DiaryWriteCommand
from swampcastle.models.drawer import (
    AddDrawerCommand,
    DeleteDrawerCommand,
    DuplicateCheckQuery,
    SearchQuery,
)
from swampcastle.models.kg import (
    AddTripleCommand,
    InvalidateCommand,
    KGQueryParams,
    TimelineQuery,
)
from swampcastle.models.record import RecordEnvelope, RecordKind
from swampcastle.services.digest import build_digest
from swampcastle.services.vault import DiaryReadQuery


# ── Wave 6: typed-record MCP input models ───────────────────────────────


class RecordAddInput(BaseModel):
    record_id: str = Field(min_length=1)
    kind: RecordKind
    content: str = Field(default="")
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecordGetInput(BaseModel):
    ids: list[str] = Field(default_factory=list)
    kind: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    include_tombstoned: bool = False


class RecordTombstoneInput(BaseModel):
    record_id: str = Field(min_length=1)
    deleted_by: str = Field(default="mcp")
    reason: str = Field(default="manual_deletion")
    grace_days: int = Field(default=90, ge=0)


class RecordGCCollectInput(BaseModel):
    record_ids: list[str] = Field(min_length=1)


# Enumerated write-trigger taxonomy (#9 design anchor): the same list on
# every write surface, so agents recognize a save moment regardless of
# which tool description they read.
WRITE_TRIGGERS = (
    "Save when the session produced: a user correction; a command or fix "
    "that worked; a debugging insight; a decision and its rationale; a "
    "stated preference; a durable fact about a project or person."
)

CANONICAL_TOOL_NAMES = (
    "status",
    "checkpoint",
    "list_wings",
    "list_rooms",
    "get_taxonomy",
    "get_aaak_spec",
    "get_origin",
    "get_curation",
    "list_catalog_cards",
    "search",
    "check_duplicate",
    "add_drawer",
    "delete_drawer",
    "kg_query",
    "kg_add",
    "kg_invalidate",
    "kg_timeline",
    "kg_stats",
    "traverse",
    "find_tunnels",
    "graph_stats",
    "diary_write",
    "diary_read",
    "record_add",
    "record_get",
    "record_tombstone",
    "record_gc_status",
    "record_gc_collect",
)

LEGACY_TOOL_ALIASES = {f"swampcastle_{name}": name for name in CANONICAL_TOOL_NAMES}


@dataclass
class ToolDef:
    description: str
    input_model: type[BaseModel] | None
    handler: Callable
    input_schema: dict[str, Any] = field(init=False)

    def __post_init__(self):
        if self.input_model:
            self.input_schema = self.input_model.model_json_schema()
        else:
            self.input_schema = {"type": "object", "properties": {}}


def resolve_tool_name(name: str) -> str:
    return LEGACY_TOOL_ALIASES.get(name, name)


def register_tools(castle: Castle) -> dict[str, ToolDef]:
    return {
        "status": ToolDef(
            description=(
                "Session digest: current project's memory (wings, rooms, recent "
                "activity), castle totals, stale wings, protocol gist. Call status "
                "first, before any task work; pass project_dir to scope it to your "
                "working directory."
            ),
            input_model=StatusInput,
            handler=lambda params=None: build_digest(
                castle, params.project_dir if params else None
            ),
        ),
        "list_wings": ToolDef(
            description="List all wings with drawer counts.",
            input_model=None,
            handler=lambda: castle.catalog.list_wings(),
        ),
        "list_rooms": ToolDef(
            description="List rooms, optionally filtered by wing.",
            input_model=None,
            handler=lambda wing=None: castle.catalog.list_rooms(wing),
        ),
        "get_taxonomy": ToolDef(
            description="Full wing → room → drawer count tree.",
            input_model=None,
            handler=lambda: castle.catalog.get_taxonomy(),
        ),
        "get_aaak_spec": ToolDef(
            description="Get the AAAK dialect specification.",
            input_model=None,
            handler=lambda: castle.catalog.get_aaak_spec(),
        ),
        "get_origin": ToolDef(
            description="Read a source-origin manifest by origin_id or source_file.",
            input_model=OriginLookupQuery,
            handler=lambda q: castle.audit.get_origin(
                origin_id=q.origin_id,
                source_file=q.source_file,
            ),
        ),
        "get_curation": ToolDef(
            description="Read local audit-overlay curation data, optionally scoped to one wing note.",
            input_model=CurationQuery,
            handler=lambda q: castle.audit.get_curation(wing=q.wing),
        ),
        "list_catalog_cards": ToolDef(
            description="Read rebuildable derived catalog cards for a wing.",
            input_model=CatalogCardsQuery,
            handler=lambda q: castle.audit.list_catalog_cards(wing=q.wing),
        ),
        "search": ToolDef(
            description="Semantic search. 'query' = keywords ONLY — do NOT include system prompts.",
            input_model=SearchQuery,
            handler=lambda q: castle.search.search(q),
        ),
        "check_duplicate": ToolDef(
            description="Check if content already exists before filing.",
            input_model=DuplicateCheckQuery,
            handler=lambda q: castle.search.check_duplicate(q),
        ),
        "checkpoint": ToolDef(
            description=(
                "File this session in one call: semantic-dedups each item, "
                "files the non-duplicates as drawers, then writes one diary "
                "entry. Preferred at session end over separate "
                "check_duplicate/add_drawer/diary_write calls. "
                + WRITE_TRIGGERS
                + " Content is verbatim — exact words, never summarized."
            ),
            input_model=CheckpointCommand,
            handler=lambda cmd: _checkpoint(castle, cmd),
        ),
        "add_drawer": ToolDef(
            description=(
                "File verbatim content into a wing/room. Call check_duplicate "
                "first — near-duplicates pollute search. For a whole-session "
                "save, prefer checkpoint. " + WRITE_TRIGGERS
            ),
            input_model=AddDrawerCommand,
            handler=lambda cmd: castle.vault.add_drawer(cmd),
        ),
        "delete_drawer": ToolDef(
            description="Delete a drawer by ID.",
            input_model=DeleteDrawerCommand,
            handler=lambda cmd: castle.vault.delete_drawer(cmd),
        ),
        "kg_query": ToolDef(
            description="Query entity relationships with optional time filtering.",
            input_model=KGQueryParams,
            handler=lambda p: castle.graph.kg_query(
                entity=p.entity,
                as_of=p.as_of,
                direction=p.direction,
            ),
        ),
        "kg_add": ToolDef(
            description=(
                "Add a fact to the knowledge graph. If it replaces an existing "
                "fact, call kg_invalidate on the old one first."
            ),
            input_model=AddTripleCommand,
            handler=lambda cmd: castle.graph.kg_add(
                subject=cmd.subject,
                predicate=cmd.predicate,
                obj=cmd.object,
                valid_from=cmd.valid_from,
                source_closet=cmd.source_closet,
            ),
        ),
        "kg_invalidate": ToolDef(
            description="Mark a fact as no longer true.",
            input_model=InvalidateCommand,
            handler=lambda cmd: castle.graph.kg_invalidate(
                subject=cmd.subject,
                predicate=cmd.predicate,
                obj=cmd.object,
                ended=cmd.ended,
            ),
        ),
        "kg_timeline": ToolDef(
            description="Chronological timeline of facts.",
            input_model=TimelineQuery,
            handler=lambda q: castle.graph.kg_timeline(entity=q.entity),
        ),
        "kg_stats": ToolDef(
            description="Knowledge graph overview.",
            input_model=None,
            handler=lambda: castle.graph.kg_stats(),
        ),
        "traverse": ToolDef(
            description="Walk the castle graph from a starting room.",
            input_model=None,
            handler=lambda start_room, max_hops=2: castle.graph.traverse(start_room, max_hops),
        ),
        "find_tunnels": ToolDef(
            description="Find rooms that bridge two wings.",
            input_model=None,
            handler=lambda wing_a=None, wing_b=None: castle.graph.find_tunnels(wing_a, wing_b),
        ),
        "graph_stats": ToolDef(
            description="Castle graph connectivity overview.",
            input_model=None,
            handler=lambda: castle.graph.graph_stats(),
        ),
        "diary_write": ToolDef(
            description=(
                "Write a diary entry for an agent — file one at session end "
                "when the session produced durable learnings. For a "
                "whole-session save (drawers + diary), prefer checkpoint. " + WRITE_TRIGGERS
            ),
            input_model=DiaryWriteCommand,
            handler=lambda cmd: castle.vault.diary_write(cmd),
        ),
        "diary_read": ToolDef(
            description="Read an agent's recent diary entries.",
            input_model=DiaryReadQuery,
            handler=lambda q: castle.vault.diary_read(q),
        ),
        # ── Wave 6: typed-record tools ──────────────────────────────────
        "record_add": ToolDef(
            description="Create a typed canonical record.",
            input_model=RecordAddInput,
            handler=lambda inp: castle.vault.add_record(RecordEnvelope(**inp.model_dump())),
        ),
        "record_get": ToolDef(
            description="Fetch records by ID or kind filter.",
            input_model=RecordGetInput,
            handler=lambda inp: _record_get(castle, inp),
        ),
        "record_tombstone": ToolDef(
            description="Mark a record as logically deleted (tombstone).",
            input_model=RecordTombstoneInput,
            handler=lambda inp: _record_tombstone(castle, inp),
        ),
        "record_gc_status": ToolDef(
            description="List record IDs pending garbage collection.",
            input_model=None,
            handler=lambda: _record_gc_status(castle),
        ),
        "record_gc_collect": ToolDef(
            description="Permanently delete records whose tombstones have expired.",
            input_model=RecordGCCollectInput,
            handler=lambda inp: _record_gc_collect(castle, inp),
        ),
    }


def _checkpoint(castle: Castle, cmd: CheckpointCommand) -> CheckpointResult:
    """Batch session save (upstream MemPalace #1851).

    Composes the existing single-item handlers, so dedup/idempotency/WAL
    behaviour is identical to calling them directly; the batch shape only
    collapses the MCP round-trips. Item validation happened in
    CheckpointCommand, so a malformed batch is rejected before anything
    is filed — no partial writes to lose from the response.
    """
    result = CheckpointResult()
    for item in cmd.items:
        try:
            dup = castle.search.check_duplicate(
                DuplicateCheckQuery(content=item.content, threshold=cmd.dedup_threshold)
            )
            if dup.is_duplicate:
                result.duplicates.append({"room": item.room, "matches": dup.matches})
                continue
        except Exception:
            # A dedup index failure must not drop the memory — verbatim
            # recall wins; add_drawer's own idempotency blocks exact dupes.
            pass
        res = castle.vault.add_drawer(
            AddDrawerCommand(
                wing=item.wing,
                room=item.room,
                content=item.content,
                added_by="checkpoint",
            )
        )
        if res.success:
            result.added.append({"drawer_id": res.drawer_id, "reason": res.reason})
        else:
            result.errors.append({"room": item.room, "error": res.reason})
    if cmd.diary is not None:
        diary_res = castle.vault.diary_write(
            DiaryWriteCommand(
                agent_name=cmd.diary.agent_name,
                entry=cmd.diary.entry,
                topic=cmd.diary.topic,
            )
        )
        result.diary = diary_res.model_dump() if hasattr(diary_res, "model_dump") else diary_res
    return result


# ── Typed-record MCP handler helpers ────────────────────────────────────


def _record_get(castle: Castle, inp: RecordGetInput) -> dict[str, Any]:
    if inp.ids:
        result = castle.vault.get_drawers(
            ids=inp.ids,
            include_tombstoned=inp.include_tombstoned,
        )
    else:
        where = {}
        if inp.kind:
            where["kind"] = inp.kind
        result = castle.vault.get_drawers(
            where=where or None,
            limit=inp.limit,
            include_tombstoned=inp.include_tombstoned,
        )
    return result


def _record_tombstone(castle: Castle, inp: RecordTombstoneInput) -> dict[str, Any]:
    tombstone_id = castle.vault.create_tombstone(
        inp.record_id,
        deleted_by=inp.deleted_by,
        reason=inp.reason,
        grace_days=inp.grace_days,
    )
    return {"tombstone_id": tombstone_id, "target_record_id": inp.record_id}


def _record_gc_status(castle: Castle) -> dict[str, Any]:
    targets = castle.vault.list_pending_gc(
        executed_at=datetime.now(timezone.utc),
    )
    return {"pending_targets": targets, "count": len(targets)}


def _record_gc_collect(castle: Castle, inp: RecordGCCollectInput) -> dict[str, Any]:
    result = castle.vault.gc_collect(
        inp.record_ids,
        executed_at=datetime.now(timezone.utc),
    )
    return {"deleted_ids": result.deleted_ids, "count": len(result.deleted_ids)}
