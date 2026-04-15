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
| Castle structure | swampcastle_status, swampcastle_get_taxonomy | Use on first interaction or when unsure where to look |

Writing

Persist only when the workflow explicitly calls for it. Choose the right tool:

| Tool | What to store | Example |
|---|---|---|
| swampcastle_add_drawer | Long-form content: decisions, discussions, specs | "We chose LanceDB because…" |
| swampcastle_kg_add | Structured facts (subject → predicate → object) | ("SwampCastle", "uses", "LanceDB") |
| swampcastle_diary_write | Agent session notes and reflections | End-of-session summary |

Before writing:
- Duplicates: call swampcastle_check_duplicate before swampcastle_add_drawer.
- Stale facts: call swampcastle_kg_invalidate before adding a replacement via swampcastle_kg_add."""

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


class CatalogService:
    def __init__(self, collection: CollectionStore, castle_path: str = ""):
        self._col = collection
        self._castle_path = castle_path

    def status(self) -> StatusResponse:
        count = self._col.count()
        wings: dict[str, int] = {}
        rooms: dict[str, int] = {}
        error_info = None
        offset = 0

        while True:
            try:
                batch = self._col.get(include=["metadatas"], limit=BATCH_SIZE, offset=offset)
                rows = batch["metadatas"]
                for m in rows:
                    w = m.get("wing", "unknown")
                    r = m.get("room", "unknown")
                    wings[w] = wings.get(w, 0) + 1
                    rooms[r] = rooms.get(r, 0) + 1
                offset += len(rows)
                if len(rows) < BATCH_SIZE:
                    break
            except Exception as e:
                error_info = f"Partial result, failed at offset {offset}: {e}"
                break

        return StatusResponse(
            total_drawers=count,
            wings=wings,
            rooms=rooms,
            castle_path=self._castle_path,
            protocol=CASTLE_PROTOCOL,
            aaak_dialect=AAAK_SPEC,
            error=error_info,
            partial=error_info is not None,
        )

    def list_wings(self) -> WingsResponse:
        wings: dict[str, int] = {}
        offset = 0
        while True:
            try:
                batch = self._col.get(include=["metadatas"], limit=BATCH_SIZE, offset=offset)
                rows = batch["metadatas"]
                for m in rows:
                    w = m.get("wing", "unknown")
                    wings[w] = wings.get(w, 0) + 1
                offset += len(rows)
                if len(rows) < BATCH_SIZE:
                    break
            except Exception as e:
                return WingsResponse(wings=wings, error=str(e))
        return WingsResponse(wings=wings)

    def list_rooms(self, wing: str | None = None) -> RoomsResponse:
        rooms: dict[str, int] = {}
        offset = 0
        while True:
            try:
                kwargs: dict = {"include": ["metadatas"], "limit": BATCH_SIZE, "offset": offset}
                if wing:
                    kwargs["where"] = {"wing": wing}
                batch = self._col.get(**kwargs)
                rows = batch["metadatas"]
                for m in rows:
                    r = m.get("room", "unknown")
                    rooms[r] = rooms.get(r, 0) + 1
                offset += len(rows)
                if len(rows) < BATCH_SIZE:
                    break
            except Exception as e:
                return RoomsResponse(wing=wing or "all", rooms=rooms, error=str(e))
        return RoomsResponse(wing=wing or "all", rooms=rooms)

    def get_taxonomy(self) -> TaxonomyResponse:
        taxonomy: dict[str, dict[str, int]] = {}
        offset = 0
        while True:
            try:
                batch = self._col.get(include=["metadatas"], limit=BATCH_SIZE, offset=offset)
                rows = batch["metadatas"]
                for m in rows:
                    w = m.get("wing", "unknown")
                    r = m.get("room", "unknown")
                    if w not in taxonomy:
                        taxonomy[w] = {}
                    taxonomy[w][r] = taxonomy[w].get(r, 0) + 1
                offset += len(rows)
                if len(rows) < BATCH_SIZE:
                    break
            except Exception as e:
                return TaxonomyResponse(taxonomy=taxonomy, error=str(e))
        return TaxonomyResponse(taxonomy=taxonomy)

    def brief(self, wing: str) -> WingBriefResponse:
        rooms: dict[str, int] = {}
        contributors: dict[str, int] = {}
        source_files: set[str] = set()
        total_drawers = 0
        offset = 0

        while True:
            try:
                batch = self._col.get(
                    include=["metadatas"],
                    where={"wing": wing},
                    limit=BATCH_SIZE,
                    offset=offset,
                )
                rows = batch["metadatas"]
                for meta in rows:
                    total_drawers += 1
                    room = meta.get("room", "unknown")
                    rooms[room] = rooms.get(room, 0) + 1

                    contributor = meta.get("contributor")
                    if contributor:
                        contributors[contributor] = contributors.get(contributor, 0) + 1

                    source_file = meta.get("source_file")
                    if source_file:
                        source_files.add(source_file)

                offset += len(rows)
                if len(rows) < BATCH_SIZE:
                    break
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
