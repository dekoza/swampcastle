"""MCP tool registry — Pydantic models as schema source of truth."""

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel

from swampcastle.castle import Castle
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
from swampcastle.services.vault import DiaryReadQuery


CANONICAL_TOOL_NAMES = (
    "status",
    "list_wings",
    "list_rooms",
    "get_taxonomy",
    "get_aaak_spec",
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
            description="Castle overview: drawers, wings, rooms, strict memory-use protocol, AAAK spec.",
            input_model=None,
            handler=lambda: castle.catalog.status(),
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
        "add_drawer": ToolDef(
            description="File verbatim content into a wing/room.",
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
            description="Add a fact to the knowledge graph.",
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
            description="Write a diary entry for an agent.",
            input_model=DiaryWriteCommand,
            handler=lambda cmd: castle.vault.diary_write(cmd),
        ),
        "diary_read": ToolDef(
            description="Read an agent's recent diary entries.",
            input_model=DiaryReadQuery,
            handler=lambda q: castle.vault.diary_read(q),
        ),
    }
