"""CatalogService — read-only castle metadata and status."""

from swampcastle.models.catalog import (
    RoomsResponse,
    StatusResponse,
    TaxonomyResponse,
    WingBriefResponse,
    WingsResponse,
)
from swampcastle.storage.base import CollectionStore

CASTLE_PROTOCOL = """SwampCastle protocol

SwampCastle is a persistent memory system accessed via MCP tools (all prefixed swampcastle_).

Core discipline

1. Never state project history, past decisions, people, or prior work from memory. Query first; if results are missing or ambiguous, say so — do not guess.
2. Scope queries with wing/room filters when the project context is known. Run swampcastle_get_taxonomy if you don't know the castle's structure yet.

Reading

| Purpose | Tool | Notes |
|---|---|---|
| Prior discussions, decisions, context | swampcastle_search | query = short keywords only, not sentences or prompts |
| Entity facts and relationships | swampcastle_kg_query | Query by entity name; use as_of for point-in-time |
| Fact timeline | swampcastle_kg_timeline | Chronological view of an entity's history |
| KG overview | swampcastle_kg_stats | Entities, triples, relationship types |
| Castle structure | swampcastle_status, swampcastle_get_taxonomy | Use on first interaction or when unsure where to look |
| Wings / rooms | swampcastle_list_wings, swampcastle_list_rooms | Drawer counts per wing/room |
| Graph traversal | swampcastle_traverse, swampcastle_find_tunnels | Walk rooms, find cross-wing bridges |
| Graph stats | swampcastle_graph_stats | Connectivity overview |
| Source origins | swampcastle_get_origin | Read manifest by origin_id or source_file |
| Curation data | swampcastle_get_curation | Local audit-overlay curation |
| Catalog cards | swampcastle_list_catalog_cards | Rebuildable derived catalog for a wing |
| Diary entries | swampcastle_diary_read | Read agent's recent diary entries |
| Typed records | swampcastle_record_get | Fetch by ID, kind filter, or with tombstone visibility |
| GC status | swampcastle_record_gc_status | List record IDs pending garbage collection |
| AAAK dialect | swampcastle_get_aaak_spec | Compressed symbolic format reference |

Writing

Persist only when the workflow explicitly calls for it. Choose the right tool:

| Tool | What to store | Example |
|---|---|---|
| swampcastle_add_drawer | Long-form content: decisions, discussions, specs | "We chose LanceDB because…" |
| swampcastle_delete_drawer | Remove a drawer by ID | — |
| swampcastle_kg_add | Structured facts (subject → predicate → object) | ("SwampCastle", "uses", "LanceDB") |
| swampcastle_kg_invalidate | Mark a fact as no longer true | — |
| swampcastle_diary_write | Agent session notes and reflections | End-of-session summary |
| swampcastle_record_add | Create a typed canonical record | kind=document, content=… |

Before writing:
- Duplicates: call swampcastle_check_duplicate before swampcastle_add_drawer.
- Stale facts: call swampcastle_kg_invalidate before adding a replacement via swampcastle_kg_add.
- Logical deletion: call swampcastle_record_tombstone to mark a record deleted (grace period applies).
- Permanent deletion: call swampcastle_record_gc_collect after the tombstone grace period expires."""

AAAK_SPEC = """AAAK is a compressed memory dialect that SwampCastle uses for efficient storage.
It is designed to be readable by both humans and LLMs without decoding.

FORMAT:
  ENTITIES: 3-letter uppercase codes. ALC=Alice, JOR=Jordan, RIL=Riley, MAX=Max, BEN=Ben.
  EMOTIONS: *action markers* before/during text. *warm*=joy, *fierce*=determined, *raw*=vulnerable, *bloom*=tenderness.
  STRUCTURE: Pipe-separated fields. FAM: family | PROJ: projects | ⚠: warnings/reminders.
  DATES: ISO format (2026-03-31). COUNTS: Nx = N mentions (e.g., 570x).
  IMPORTANCE: ★ to ★★★★★ (1-5 scale).
  HALLS: hall_facts, hall_events, hall_discoveries, hall_preferences, hall_advice.
  WINGS: wing_user, wing_agent, wing_team, wing_code, wing_myproject.
  ROOMS: Hyphenated slugs representing named ideas (e.g., chromadb-setup, gpu-pricing).

EXAMPLE:
  FAM: ALC→♡JOR | 2D(kids): RIL(18,sports) MAX(11,chess+swimming) | BEN(contributor)

Read AAAK naturally — expand codes mentally, treat *markers* as emotional context.
When WRITING AAAK: use entity codes, mark emotions, keep structure tight."""

BATCH_SIZE = 5000


class _CatalogView:
    """Immutable snapshot of catalog metadata from a single collection scan."""
    __slots__ = ("wings", "rooms", "taxonomy")

    def __init__(self, metas: list[dict]):
        wings: dict[str, int] = {}
        rooms: dict[str, int] = {}
        taxonomy: dict[str, dict[str, int]] = {}
        for m in metas:
            w = m.get("wing", "unknown")
            r = m.get("room", "unknown")
            wings[w] = wings.get(w, 0) + 1
            rooms[r] = rooms.get(r, 0) + 1
            if w not in taxonomy:
                taxonomy[w] = {}
            taxonomy[w][r] = taxonomy[w].get(r, 0) + 1
        self.wings = wings
        self.rooms = rooms
        self.taxonomy = taxonomy


class CatalogService:
    def __init__(self, collection: CollectionStore, castle_path: str = ""):
        self._col = collection
        self._castle_path = castle_path
        self._view_cache: _CatalogView | None = None

    def _invalidate_view(self) -> None:
        self._view_cache = None

    def _get_view(self) -> _CatalogView:
        if self._view_cache is None:
            self._view_cache = _CatalogView(self._scan_all())
        return self._view_cache

    def _scan_all(self, *, where: dict | None = None) -> list[dict]:
        """Fetch all metadata rows using offset pagination.

        Returns a flat list of metadata dicts.  Callers that only need to
        iterate once can use the generator variant ``_iter_all`` instead.
        """
        rows: list[dict] = []
        offset = 0
        while True:
            batch = self._col.get(
                include=["metadatas"],
                limit=BATCH_SIZE,
                offset=offset,
                where=where,
            )
            metas = batch.get("metadatas", [])
            rows.extend(metas)
            if len(metas) < BATCH_SIZE:
                break
            offset += len(metas)
        return rows

    def status(self) -> StatusResponse:
        count = self._col.count()
        error_info = None
        view = _CatalogView([])
        try:
            view = self._get_view()
        except Exception as e:
            error_info = f"Partial result: {e}"

        return StatusResponse(
            total_drawers=count,
            wings=view.wings,
            rooms=view.rooms,
            castle_path=self._castle_path,
            protocol=CASTLE_PROTOCOL,
            aaak_dialect=AAAK_SPEC,
            error=error_info,
            partial=error_info is not None,
        )

    def list_wings(self) -> WingsResponse:
        try:
            view = self._get_view()
            return WingsResponse(wings=view.wings)
        except Exception as e:
            return WingsResponse(wings={}, error=str(e))

    def list_rooms(self, wing: str | None = None) -> RoomsResponse:
        try:
            view = self._get_view()
            if wing:
                rooms = dict(view.taxonomy.get(wing, {}))
            else:
                rooms = dict(view.rooms)
            return RoomsResponse(wing=wing or "all", rooms=rooms)
        except Exception as e:
            return RoomsResponse(wing=wing or "all", rooms={}, error=str(e))

    def get_taxonomy(self) -> TaxonomyResponse:
        try:
            view = self._get_view()
            return TaxonomyResponse(taxonomy=view.taxonomy)
        except Exception as e:
            return TaxonomyResponse(taxonomy={}, error=str(e))

    def brief(self, wing: str) -> WingBriefResponse:
        rooms: dict[str, int] = {}
        contributors: dict[str, int] = {}
        source_files: set[str] = set()
        total_drawers = 0
        try:
            for meta in self._scan_all(where={"wing": wing}):
                total_drawers += 1
                room = meta.get("room", "unknown")
                rooms[room] = rooms.get(room, 0) + 1

                contributor = meta.get("contributor")
                if contributor:
                    contributors[contributor] = contributors.get(contributor, 0) + 1

                source_file = meta.get("source_file")
                if source_file:
                    source_files.add(source_file)
        except Exception as e:
            return WingBriefResponse(
                wing=wing,
                total_drawers=total_drawers,
                rooms=rooms,
                contributors=contributors,
                source_files=len(source_files),
                error=str(e),
            )

        return WingBriefResponse(
            wing=wing,
            total_drawers=total_drawers,
            rooms=rooms,
            contributors=contributors,
            source_files=len(source_files),
        )

    def get_aaak_spec(self) -> str:
        return AAAK_SPEC
