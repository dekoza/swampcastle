"""GraphService — knowledge graph + palace graph traversal."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

from swampcastle.audit.curation import load_tunnel_curation, TunnelCuration
from swampcastle.models.kg import (
    InvalidateResult,
    KGQueryResult,
    KGStatsResult,
    TimelineResult,
    TripleResult,
)
from swampcastle.storage.base import CollectionStore, GraphStore
from swampcastle.wal import WalWriter


@dataclass(frozen=True)
class _PalaceNode:
    wings: tuple[str, ...]
    halls: tuple[str, ...]
    count: int
    dates: tuple[str, ...]


@dataclass
class PalaceGraph:
    """Immutable snapshot of the palace room graph, loaded once at construction.

    Nodes are keyed by room name. Edges connect rooms that share wings.
    Curation policy is baked in at construction time.
    """
    nodes: dict[str, _PalaceNode] = field(default_factory=dict)
    edges: list[dict] = field(default_factory=list)
    curation: TunnelCuration | None = None

    @classmethod
    def build(cls, collection: CollectionStore, castle_path: str | None = None) -> "PalaceGraph":
        """Scan collection metadata and build the palace graph."""
        total = collection.count()
        room_data: dict[str, dict] = defaultdict(
            lambda: {"wings": set(), "halls": set(), "count": 0, "dates": set()}
        )
        offset = 0
        while offset < max(total, 1):
            batch = collection.get(limit=1000, offset=offset, include=["metadatas"])
            if not batch["ids"]:
                break
            for meta in batch["metadatas"]:
                room = meta.get("room", "")
                wing = meta.get("wing", "")
                hall = meta.get("hall", "")
                dt = meta.get("date", "")
                if room and room != "general" and wing:
                    room_data[room]["wings"].add(wing)
                    if hall:
                        room_data[room]["halls"].add(hall)
                    if dt:
                        room_data[room]["dates"].add(dt)
                    room_data[room]["count"] += 1
            offset += len(batch["ids"])

        nodes: dict[str, _PalaceNode] = {}
        edges: list[dict] = []
        for room, data in room_data.items():
            wings = sorted(data["wings"])
            nodes[room] = _PalaceNode(
                wings=tuple(wings),
                halls=tuple(sorted(data["halls"])),
                count=data["count"],
                dates=tuple(sorted(data["dates"])[-5:]) if data["dates"] else (),
            )
            if len(wings) >= 2:
                for i, wa in enumerate(wings):
                    for wb in wings[i + 1:]:
                        for hall in data["halls"] or [""]:
                            edges.append({
                                "room": room,
                                "wing_a": wa,
                                "wing_b": wb,
                                "hall": hall,
                                "count": data["count"],
                            })

        curation = load_tunnel_curation(castle_path) if castle_path else None
        return cls(nodes=nodes, edges=edges, curation=curation)

    def compute_curated_tunnels(self) -> list[dict]:
        """Compute curated tunnel list from edges + curation policy."""
        grouped: dict[tuple[str, tuple[str, str]], dict] = {}
        for edge in self.edges:
            wings = tuple(sorted((edge["wing_a"], edge["wing_b"])))
            key = (edge["room"], wings)
            item = grouped.setdefault(
                key,
                {"room": edge["room"], "wings": list(wings), "halls": set(), "count": edge["count"]},
            )
            hall = edge.get("hall")
            if hall:
                item["halls"].add(hall)
            item["count"] = max(item["count"], edge["count"])

        if self.curation is not None:
            denied = {rule.key() for rule in self.curation.deny}
            boosted = {rule.key(): rule.weight for rule in self.curation.boost}
            grouped = {k: v for k, v in grouped.items() if k not in denied}
            for rule in self.curation.allow:
                key = rule.key()
                if key in denied:
                    continue
                entry = grouped.setdefault(
                    key,
                    {"room": rule.room, "wings": list(rule.normalized_wings()),
                     "halls": set(), "count": 0, "policy": "allow"},
                )
                entry.setdefault("policy", "allow")
            for key, weight in boosted.items():
                if key in grouped:
                    grouped[key]["boost"] = weight

        tunnels = []
        for tunnel in grouped.values():
            item = dict(tunnel)
            item["halls"] = sorted(item.get("halls", []))
            tunnels.append(item)
        tunnels.sort(
            key=lambda t: (-(t.get("count", 0) + t.get("boost", 0.0)), t["room"], t["wings"])
        )
        return tunnels


class GraphService:
    def __init__(
        self,
        graph: GraphStore,
        collection: CollectionStore,
        wal: WalWriter,
        castle_path: str | None = None,
    ):
        self._graph = graph
        self._col = collection
        self._wal = wal
        self._castle_path = castle_path
        self._palace_graph: PalaceGraph | None = None

    def invalidate_cache(self) -> None:
        """Drop the cached palace graph."""
        self._palace_graph = None

    def _get_palace_graph(self) -> PalaceGraph:
        if self._palace_graph is None:
            self._palace_graph = PalaceGraph.build(self._col, self._castle_path)
        return self._palace_graph

    def kg_query(
        self, entity: str, as_of: str | None = None, direction: str = "both"
    ) -> KGQueryResult:
        results = self._graph.query_entity(name=entity, as_of=as_of, direction=direction)
        return KGQueryResult(
            entity=entity,
            as_of=as_of,
            facts=results,
            count=len(results),
        )

    def kg_add(
        self,
        subject: str,
        predicate: str,
        obj: str,
        valid_from: str | None = None,
        source_closet: str | None = None,
    ) -> TripleResult:
        self._wal.log(
            "kg_add",
            {
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "valid_from": valid_from,
            },
        )
        triple_id = self._graph.add_triple(
            subject=subject,
            predicate=predicate,
            obj=obj,
            valid_from=valid_from,
            source_closet=source_closet,
        )
        return TripleResult(
            success=True,
            triple_id=triple_id,
            fact=f"{subject} → {predicate} → {obj}",
        )

    def kg_invalidate(
        self, subject: str, predicate: str, obj: str, ended: str | None = None
    ) -> InvalidateResult:
        ended = ended or str(date.today())
        self._wal.log(
            "kg_invalidate",
            {
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "ended": ended,
            },
        )
        self._graph.invalidate(
            subject=subject,
            predicate=predicate,
            obj=obj,
            ended=ended,
        )
        return InvalidateResult(
            success=True,
            fact=f"{subject} → {predicate} → {obj}",
            ended=ended,
        )

    def kg_timeline(self, entity: str | None = None) -> TimelineResult:
        results = self._graph.timeline(entity_name=entity)
        return TimelineResult(
            entity=entity or "all",
            timeline=results,
            count=len(results),
        )

    def kg_stats(self) -> KGStatsResult:
        raw = self._graph.stats()
        return KGStatsResult(**raw)

    def traverse(self, start_room: str, max_hops: int = 2) -> list[dict]:
        pg = self._get_palace_graph()
        if start_room not in pg.nodes:
            return []

        start = pg.nodes[start_room]
        visited = {start_room}
        results = [
            {
                "room": start_room,
                "wings": list(start.wings),
                "halls": list(start.halls),
                "count": start.count,
                "hop": 0,
            }
        ]

        frontier = [(start_room, 0)]
        while frontier:
            current_room, depth = frontier.pop(0)
            if depth >= max_hops:
                continue
            current_wings = set(pg.nodes.get(current_room, _PalaceNode((), (), 0, ())).wings)
            for room, node in pg.nodes.items():
                if room in visited:
                    continue
                shared = current_wings & set(node.wings)
                if shared:
                    visited.add(room)
                    results.append(
                        {
                            "room": room,
                            "wings": list(node.wings),
                            "halls": list(node.halls),
                            "count": node.count,
                            "hop": depth + 1,
                            "connected_via": sorted(shared),
                        }
                    )
                    if depth + 1 < max_hops:
                        frontier.append((room, depth + 1))

        results.sort(key=lambda x: (x["hop"], -x["count"]))
        return results[:50]

    def find_tunnels(self, wing_a: str | None = None, wing_b: str | None = None) -> list[dict]:
        pg = self._get_palace_graph()
        tunnels = pg.compute_curated_tunnels()
        if wing_a:
            tunnels = [t for t in tunnels if wing_a in t["wings"]]
        if wing_b:
            tunnels = [t for t in tunnels if wing_b in t["wings"]]
        return tunnels[:50]

    def graph_stats(self) -> dict:
        pg = self._get_palace_graph()
        curated_tunnels = pg.compute_curated_tunnels()
        tunnel_rooms = len({(t["room"], tuple(t["wings"])) for t in curated_tunnels})
        wing_counts = Counter()
        for node in pg.nodes.values():
            for w in node.wings:
                wing_counts[w] += 1
        return {
            "total_rooms": len(pg.nodes),
            "tunnel_rooms": tunnel_rooms,
            "total_edges": len(curated_tunnels) or len(pg.edges),
            "rooms_per_wing": dict(wing_counts.most_common()),
        }
