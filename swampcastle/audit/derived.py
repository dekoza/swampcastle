"""Rebuildable derived audit artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from swampcastle.models.derived import CatalogCard, SearchTrace
from swampcastle.models.drawer import SearchQuery, SearchResponse

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{3,}")
_ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z0-9_-]{2,}\b")
_STOP_WORDS = {
    "about",
    "after",
    "again",
    "auth",
    "because",
    "been",
    "between",
    "build",
    "castle",
    "clerk",
    "could",
    "does",
    "from",
    "have",
    "into",
    "just",
    "local",
    "migration",
    "notes",
    "over",
    "project",
    "room",
    "should",
    "source",
    "swampcastle",
    "that",
    "their",
    "there",
    "these",
    "they",
    "this",
    "through",
    "under",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _derived_root(castle_path: str | Path) -> Path:
    return Path(castle_path).expanduser().resolve() / ".swampcastle" / "derived"


def _catalog_dir(castle_path: str | Path) -> Path:
    return _derived_root(castle_path) / "catalog"


def _trace_dir(castle_path: str | Path) -> Path:
    return _derived_root(castle_path) / "traces"


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text) if token.lower() not in _STOP_WORDS]


def _top_topic(texts: list[str], room: str) -> str:
    counts = Counter()
    for text in texts:
        counts.update(_tokenize(text))
    if not counts:
        return room or "general"
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:4]
    return " ".join(token for token, _ in ranked)


def _top_entities(texts: list[str]) -> list[str]:
    counts = Counter()
    for text in texts:
        counts.update(_ENTITY_RE.findall(text))
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))[:5]
    return [entity for entity, _ in ranked]


def _write_jsonl_cards(path: Path, cards: list[CatalogCard]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".jsonl.tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        for card in cards:
            handle.write(card.model_dump_json())
            handle.write("\n")
    tmp_path.replace(path)


def _group_cards(collection, *, wing: str | None = None, batch_size: int = 1000) -> dict[str, dict]:
    groups: dict[str, dict[tuple[str, str], dict[str, Any]]] = defaultdict(dict)
    total = collection.count()
    offset = 0
    while offset < max(total, 1):
        batch = collection.get(limit=batch_size, offset=offset, include=["documents", "metadatas"])
        ids = batch.get("ids", [])
        if not ids:
            break
        for drawer_id, document, metadata in zip(
            ids, batch.get("documents", []), batch.get("metadatas", [])
        ):
            drawer_wing = metadata.get("wing", "")
            if not drawer_wing:
                continue
            if wing and drawer_wing != wing:
                continue
            room = metadata.get("room", "general") or "general"
            source_file = metadata.get("source_file", "") or ""
            key = (room, source_file)
            bucket = groups[drawer_wing].setdefault(
                key,
                {"texts": [], "drawer_ids": set(), "source_files": set()},
            )
            bucket["texts"].append(document or "")
            bucket["drawer_ids"].add(drawer_id)
            if source_file:
                bucket["source_files"].add(source_file)
        offset += len(ids)
    return groups


def rebuild_catalog(
    collection, castle_path: str | Path, *, wing: str | None = None
) -> dict[str, Any]:
    groups = _group_cards(collection, wing=wing)
    catalog_dir = _catalog_dir(castle_path)
    catalog_dir.mkdir(parents=True, exist_ok=True)

    cards_by_wing: dict[str, list[CatalogCard]] = {}
    for drawer_wing, entries in groups.items():
        cards = []
        for (room, _source_file), bucket in sorted(entries.items()):
            texts = sorted(bucket["texts"])
            cards.append(
                CatalogCard(
                    wing=drawer_wing,
                    room=room,
                    topic=_top_topic(texts, room),
                    entities=_top_entities(texts),
                    drawer_ids=sorted(bucket["drawer_ids"]),
                    source_files=sorted(bucket["source_files"]),
                )
            )
        cards.sort(key=lambda card: (card.room, card.topic, card.source_files, card.drawer_ids))
        cards_by_wing[drawer_wing] = cards
        _write_jsonl_cards(catalog_dir / f"{drawer_wing}.jsonl", cards)

    existing_files = sorted(catalog_dir.glob("*.jsonl"))
    if wing:
        target = catalog_dir / f"{wing}.jsonl"
        if wing not in cards_by_wing and target.exists():
            target.unlink()
    else:
        active = {f"{drawer_wing}.jsonl" for drawer_wing in cards_by_wing}
        for path in existing_files:
            if path.name not in active:
                path.unlink()

    return {
        "wings_rebuilt": len(cards_by_wing),
        "cards_written": sum(len(cards) for cards in cards_by_wing.values()),
        "wings": {drawer_wing: len(cards) for drawer_wing, cards in cards_by_wing.items()},
    }


def load_catalog_cards(castle_path: str | Path, wing: str) -> list[CatalogCard]:
    path = _catalog_dir(castle_path) / f"{wing}.jsonl"
    if not path.is_file():
        return []
    cards = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            cards.append(CatalogCard.model_validate_json(line))
    return cards


def _trace_id(query: SearchQuery, response: SearchResponse) -> str:
    payload = json.dumps(
        {
            "request": query.model_dump(mode="json"),
            "response": response.model_dump(mode="json"),
            "created_at": _utc_now_iso(),
        },
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"trace_{digest}"


def write_search_trace(
    castle_path: str | Path,
    query: SearchQuery,
    response: SearchResponse,
) -> Path:
    trace = SearchTrace(
        trace_id=_trace_id(query, response),
        created_at=_utc_now_iso(),
        request=query,
        response=response,
    )
    path = _trace_dir(castle_path) / f"{trace.trace_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(trace.model_dump(mode="json"), handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp_path.replace(path)
    return path


def load_search_trace(path: str | Path) -> SearchTrace:
    with open(Path(path), encoding="utf-8") as handle:
        payload = json.load(handle)
    return SearchTrace.model_validate(payload)
