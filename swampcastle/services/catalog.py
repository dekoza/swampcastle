"""CatalogService — read-only castle metadata and status."""

from swampcastle.models.catalog import (
    RoomsResponse,
    TaxonomyResponse,
    WingBriefResponse,
    WingsResponse,
)
from swampcastle.storage.base import CollectionStore

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
    __slots__ = ("wings", "rooms", "taxonomy", "wing_last")

    def __init__(self, metas: list[dict]):
        wings: dict[str, int] = {}
        rooms: dict[str, int] = {}
        taxonomy: dict[str, dict[str, int]] = {}
        wing_last: dict[str, str | None] = {}
        for m in metas:
            w = m.get("wing", "unknown")
            r = m.get("room", "unknown")
            wings[w] = wings.get(w, 0) + 1
            rooms[r] = rooms.get(r, 0) + 1
            if w not in taxonomy:
                taxonomy[w] = {}
            taxonomy[w][r] = taxonomy[w].get(r, 0) + 1
            # ISO timestamps compare lexicographically; vault writes
            # created_at, mining/diary write filed_at
            ts = m.get("created_at") or m.get("filed_at") or None
            prev = wing_last.get(w)
            if ts and (prev is None or ts > prev):
                wing_last[w] = ts
            elif w not in wing_last:
                wing_last[w] = None
        self.wings = wings
        self.rooms = rooms
        self.taxonomy = taxonomy
        self.wing_last = wing_last


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

    def wing_activity(self) -> dict[str, str | None]:
        """Newest drawer timestamp per wing (ISO string), None when undated."""
        return dict(self._get_view().wing_last)

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
