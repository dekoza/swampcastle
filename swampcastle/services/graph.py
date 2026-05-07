"""GraphService — knowledge graph + palace graph traversal."""

from collections import Counter, defaultdict
from datetime import date

from swampcastle.audit.curation import load_tunnel_curation
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
        self._summary_cache: tuple[dict, list[dict]] | None = None
        self._summary_cache_count: int | None = None

    def invalidate_cache(self) -> None:
        """Drop the cached room graph summary.

        Called after drawer writes/deletes so read-only graph operations do not
        rebuild the entire summary unless the collection actually changed.
        """
        self._summary_cache = None
        self._summary_cache_count = None

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

    def _get_graph_summary(self) -> tuple[dict, list[dict]]:
        """Return a cached graph summary when the collection size is unchanged."""
        total = self._col.count()
        if self._summary_cache is not None and self._summary_cache_count == total:
            return self._summary_cache

        summary = self._build_graph()
        self._summary_cache = summary
        self._summary_cache_count = total
        return summary

    def traverse(self, start_room: str, max_hops: int = 2) -> list[dict]:
        nodes, edges = self._get_graph_summary()
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

    def _curated_tunnels(self) -> list[dict]:
        nodes, edges = self._get_graph_summary()
        grouped: dict[tuple[str, tuple[str, str]], dict] = {}

        for edge in edges:
            wings = tuple(sorted((edge["wing_a"], edge["wing_b"])))
            key = (edge["room"], wings)
            item = grouped.setdefault(
                key,
                {
                    "room": edge["room"],
                    "wings": list(wings),
                    "halls": set(),
                    "count": edge["count"],
                },
            )
            hall = edge.get("hall")
            if hall:
                item["halls"].add(hall)
            item["count"] = max(item["count"], edge["count"])

        if self._castle_path:
            policy = load_tunnel_curation(self._castle_path)
            denied = {rule.key() for rule in policy.deny}
            boosted = {rule.key(): rule.weight for rule in policy.boost}

            grouped = {key: value for key, value in grouped.items() if key not in denied}

            for rule in policy.allow:
                key = rule.key()
                if key in denied:
                    continue
                entry = grouped.setdefault(
                    key,
                    {
                        "room": rule.room,
                        "wings": list(rule.normalized_wings()),
                        "halls": set(),
                        "count": 0,
                        "policy": "allow",
                    },
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
            key=lambda item: (
                -(item.get("count", 0) + item.get("boost", 0.0)),
                item["room"],
                item["wings"],
            )
        )
        return tunnels

    def find_tunnels(self, wing_a: str | None = None, wing_b: str | None = None) -> list[dict]:
        tunnels = []
        for tunnel in self._curated_tunnels():
            wings = tunnel["wings"]
            if wing_a and wing_a not in wings:
                continue
            if wing_b and wing_b not in wings:
                continue
            tunnels.append(tunnel)
        return tunnels[:50]

    def graph_stats(self) -> dict:
        nodes, edges = self._get_graph_summary()
        curated_tunnels = self._curated_tunnels()
        tunnel_rooms = len({(tunnel["room"], tuple(tunnel["wings"])) for tunnel in curated_tunnels})
        wing_counts = Counter()
        for data in nodes.values():
            for w in data["wings"]:
                wing_counts[w] += 1
        return {
            "total_rooms": len(nodes),
            "tunnel_rooms": tunnel_rooms,
            "total_edges": len(curated_tunnels) or len(edges),
            "rooms_per_wing": dict(wing_counts.most_common()),
        }
