"""GraphService — knowledge graph + palace graph traversal."""

from collections import Counter, defaultdict
from datetime import date

from swampcastle.models.kg import (
    InvalidateResult,
    KGQueryResult,
    KGStatsResult,
    TimelineResult,
    TripleResult,
)
from swampcastle.storage.base import CollectionStore, GraphStore
from swampcastle.wal import WalWriter


class GraphService:
    def __init__(self, graph: GraphStore, collection: CollectionStore, wal: WalWriter):
        self._graph = graph
        self._col = collection
        self._wal = wal

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

    def _build_graph(self):
        total = self._col.count()
        room_data = defaultdict(
            lambda: {"wings": set(), "halls": set(), "count": 0, "dates": set()}
        )

        offset = 0
        while offset < max(total, 1):
            batch = self._col.get(limit=1000, offset=offset, include=["metadatas"])
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

        edges = []
        for room, data in room_data.items():
            wings = sorted(data["wings"])
            if len(wings) >= 2:
                for i, wa in enumerate(wings):
                    for wb in wings[i + 1 :]:
                        for hall in data["halls"] or [""]:
                            edges.append(
                                {
                                    "room": room,
                                    "wing_a": wa,
                                    "wing_b": wb,
                                    "hall": hall,
                                    "count": data["count"],
                                }
                            )

        nodes = {}
        for room, data in room_data.items():
            nodes[room] = {
                "wings": sorted(data["wings"]),
                "halls": sorted(data["halls"]),
                "count": data["count"],
                "dates": sorted(data["dates"])[-5:] if data["dates"] else [],
            }
        return nodes, edges

    def traverse(self, start_room: str, max_hops: int = 2) -> list[dict]:
        nodes, edges = self._build_graph()
        if start_room not in nodes:
            return []

        start = nodes[start_room]
        visited = {start_room}
        results = [
            {
                "room": start_room,
                "wings": start["wings"],
                "halls": start["halls"],
                "count": start["count"],
                "hop": 0,
            }
        ]

        frontier = [(start_room, 0)]
        while frontier:
            current_room, depth = frontier.pop(0)
            if depth >= max_hops:
                continue
            current_wings = set(nodes.get(current_room, {}).get("wings", []))
            for room, data in nodes.items():
                if room in visited:
                    continue
                shared = current_wings & set(data["wings"])
                if shared:
                    visited.add(room)
                    results.append(
                        {
                            "room": room,
                            "wings": data["wings"],
                            "halls": data["halls"],
                            "count": data["count"],
                            "hop": depth + 1,
                            "connected_via": sorted(shared),
                        }
                    )
                    if depth + 1 < max_hops:
                        frontier.append((room, depth + 1))

        results.sort(key=lambda x: (x["hop"], -x["count"]))
        return results[:50]

    def find_tunnels(self, wing_a: str | None = None, wing_b: str | None = None) -> list[dict]:
        nodes, _ = self._build_graph()
        tunnels = []
        for room, data in nodes.items():
            wings = data["wings"]
            if len(wings) < 2:
                continue
            if wing_a and wing_a not in wings:
                continue
            if wing_b and wing_b not in wings:
                continue
            tunnels.append(
                {
                    "room": room,
                    "wings": wings,
                    "halls": data["halls"],
                    "count": data["count"],
                }
            )
        tunnels.sort(key=lambda x: -x["count"])
        return tunnels[:50]

    def graph_stats(self) -> dict:
        nodes, edges = self._build_graph()
        tunnel_rooms = sum(1 for n in nodes.values() if len(n["wings"]) >= 2)
        wing_counts = Counter()
        for data in nodes.values():
            for w in data["wings"]:
                wing_counts[w] += 1
        return {
            "total_rooms": len(nodes),
            "tunnel_rooms": tunnel_rooms,
            "total_edges": len(edges),
            "rooms_per_wing": dict(wing_counts.most_common()),
        }
