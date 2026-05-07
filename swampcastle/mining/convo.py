#!/usr/bin/env python3
"""
convo_miner.py — Mine conversations into the palace.

Ingests chat exports (Claude Code, ChatGPT, Slack, plain text transcripts).
Normalizes format, chunks by exchange pair (Q+A = one unit), files to palace.

Same palace as project mining. Different ingest strategy.
"""

import os
import sys
import hashlib
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from ..audit.curation import resolve_wing_hint
from ..audit.origin import detect_source_origin, origin_metadata, write_origin_manifest
from .adapters import ConversationExportsAdapter
from .normalize import normalize
from .contributor import detect_contributor
from .kg_extract import persist_kg_proposals_for_wing
from ..project_config import resolve_project_config
from ..settings import CastleSettings
from ..storage import StorageFactory, factory_from_settings

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    ".next",
    "coverage",
    ".swampcastle",
}


def _file_already_mined(collection, source_file: str, *, check_mtime: bool = False) -> bool:
    try:
        results = collection.get(where={"source_file": source_file}, limit=1)
        if not results.get("ids"):
            return False
        if not check_mtime:
            return True

        stored_meta = results.get("metadatas", [{}])[0]
        stored_mtime = stored_meta.get("source_mtime")
        if stored_mtime is None:
            return False

        current_mtime = os.stat(source_file).st_mtime_ns
        return int(stored_mtime) == int(current_mtime)
    except Exception:
        return False


def _purge_source_file(collection, source_file: str, *, batch_size: int = 500) -> None:
    while True:
        rows = collection.get(where={"source_file": source_file}, limit=batch_size)
        ids = rows.get("ids", [])
        if not ids:
            return
        collection.delete(ids=ids)


# File types that might contain conversations
CONVO_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".jsonl",
}

MIN_CHUNK_SIZE = 30
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB — skip files larger than this


# =============================================================================
# CHUNKING — exchange pairs for conversations
# =============================================================================


def chunk_exchanges(content: str) -> list:
    """
    Chunk by exchange pair: one > turn + AI response = one unit.
    Falls back to paragraph chunking if no > markers.
    """
    lines = content.split("\n")
    quote_lines = sum(1 for line in lines if line.strip().startswith(">"))

    if quote_lines >= 3:
        return _chunk_by_exchange(lines)
    else:
        return _chunk_by_paragraph(content)


def _chunk_by_exchange(lines: list) -> list:
    """One user turn (>) + the AI response that follows = one chunk."""
    chunks = []
    i = 0

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith(">"):
            user_turn = line.strip()
            i += 1

            ai_lines = []
            while i < len(lines):
                next_line = lines[i]
                if next_line.strip().startswith(">") or next_line.strip().startswith("---"):
                    break
                if next_line.strip():
                    ai_lines.append(next_line.strip())
                i += 1

            ai_response = " ".join(ai_lines[:8])
            content = f"{user_turn}\n{ai_response}" if ai_response else user_turn

            if len(content.strip()) > MIN_CHUNK_SIZE:
                chunks.append(
                    {
                        "content": content,
                        "chunk_index": len(chunks),
                    }
                )
        else:
            i += 1

    return chunks


def _chunk_by_paragraph(content: str) -> list:
    """Fallback: chunk by paragraph breaks."""
    chunks = []
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

    # If no paragraph breaks and long content, chunk by line groups
    if len(paragraphs) <= 1 and content.count("\n") > 20:
        lines = content.split("\n")
        for i in range(0, len(lines), 25):
            group = "\n".join(lines[i : i + 25]).strip()
            if len(group) > MIN_CHUNK_SIZE:
                chunks.append({"content": group, "chunk_index": len(chunks)})
        return chunks

    for para in paragraphs:
        if len(para) > MIN_CHUNK_SIZE:
            chunks.append({"content": para, "chunk_index": len(chunks)})

    return chunks


# =============================================================================
# ROOM DETECTION — topic-based for conversations
# =============================================================================

TOPIC_KEYWORDS = {
    "technical": [
        "code",
        "python",
        "function",
        "bug",
        "error",
        "api",
        "database",
        "server",
        "deploy",
        "git",
        "test",
        "debug",
        "refactor",
    ],
    "architecture": [
        "architecture",
        "design",
        "pattern",
        "structure",
        "schema",
        "interface",
        "module",
        "component",
        "service",
        "layer",
    ],
    "planning": [
        "plan",
        "roadmap",
        "milestone",
        "deadline",
        "priority",
        "sprint",
        "backlog",
        "scope",
        "requirement",
        "spec",
    ],
    "decisions": [
        "decided",
        "chose",
        "picked",
        "switched",
        "migrated",
        "replaced",
        "trade-off",
        "alternative",
        "option",
        "approach",
    ],
    "problems": [
        "problem",
        "issue",
        "broken",
        "failed",
        "crash",
        "stuck",
        "workaround",
        "fix",
        "solved",
        "resolved",
    ],
}


def detect_convo_room(content: str) -> str:
    """Score conversation content against topic keywords."""
    content_lower = content[:3000].lower()
    scores = {}
    for room, keywords in TOPIC_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in content_lower)
        if score > 0:
            scores[room] = score
    if scores:
        return max(scores, key=scores.get)
    return "general"


# =============================================================================
# PALACE OPERATIONS
# =============================================================================


# =============================================================================
# SCAN FOR CONVERSATION FILES
# =============================================================================


def scan_convos(convo_dir: str) -> list:
    """Find all potential conversation files."""
    convo_path = Path(convo_dir).expanduser().resolve()
    if convo_path.is_file():
        if convo_path.name.endswith(".meta.json"):
            return []
        if convo_path.suffix.lower() not in CONVO_EXTENSIONS:
            return []
        if convo_path.is_symlink():
            return []
        try:
            if convo_path.stat().st_size > MAX_FILE_SIZE:
                return []
        except OSError:
            return []
        return [convo_path]

    files = []
    for root, dirs, filenames in os.walk(convo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for filename in filenames:
            if filename.endswith(".meta.json"):
                continue
            filepath = Path(root) / filename
            if filepath.suffix.lower() in CONVO_EXTENSIONS:
                # Skip symlinks and oversized files
                if filepath.is_symlink():
                    continue
                try:
                    if filepath.stat().st_size > MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue
                files.append(filepath)
    return files


# =============================================================================
# MINE CONVERSATIONS
# =============================================================================


def _load_contributor_context(convo_path: Path):
    team = None
    registry = None
    config_root = convo_path.parent if convo_path.is_file() else convo_path
    config_path = resolve_project_config(config_root)
    if config_path is None:
        return team, registry

    import yaml

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    team = config.get("team")
    if not team:
        return team, registry

    try:
        from ..entity_registry import EntityRegistry

        registry = EntityRegistry.load()
    except Exception:
        registry = None
    return team, registry


def _extract_chunks(content: str, extract_mode: str):
    if extract_mode == "general":
        from .general_extractor import extract_memories

        return extract_memories(content)
    return chunk_exchanges(content)


def _source_mtime(source_file: str) -> int | None:
    try:
        return os.stat(source_file).st_mtime_ns
    except OSError:
        return None


def _analyze_convo_file(
    filepath: Path,
    *,
    palace_path: str,
    convo_path: Path,
    team,
    registry,
    extract_mode: str,
):
    content = normalize(str(filepath))
    if not content or len(content.strip()) < MIN_CHUNK_SIZE:
        return None

    chunks = _extract_chunks(content, extract_mode)
    if not chunks:
        return None

    room = detect_convo_room(content) if extract_mode != "general" else None
    contributor = detect_contributor(filepath, convo_path, team=team, registry=registry)
    origin = detect_source_origin(str(filepath), castle_path=palace_path)

    return {
        "content": content,
        "chunks": chunks,
        "room": room,
        "contributor": contributor,
        "origin": origin,
    }


def _record_dry_run(result, extract_mode: str, room_counts: dict) -> int:
    filepath = result.filepath
    chunks = result.chunks
    room = result.room

    if extract_mode == "general":
        from collections import Counter

        type_counts = Counter(c.get("memory_type", "general") for c in chunks)
        types_str = ", ".join(f"{t}:{n}" for t, n in type_counts.most_common())
        print(f"    [DRY RUN] {filepath.name} → {len(chunks)} memories ({types_str})")
        for chunk in chunks:
            room_counts[chunk.get("memory_type", "general")] += 1
        return len(chunks)

    print(f"    [DRY RUN] {filepath.name} → room:{room} ({len(chunks)} drawers)")
    room_counts[room] += 1
    return len(chunks)


def _extract_kg_proposals_if_enabled(
    *,
    extract_kg_proposals: bool,
    dry_run: bool,
    storage_factory: StorageFactory | None,
    collection,
    palace_path: str,
    wing: str,
) -> int:
    if not extract_kg_proposals or dry_run or storage_factory is None or collection is None:
        return 0
    return persist_kg_proposals_for_wing(
        palace_path=palace_path,
        storage_factory=storage_factory,
        collection=collection,
        wing=wing,
    )


def mine_convos(
    convo_dir: str,
    palace_path: str,
    wing: str = None,
    agent: str = "swampcastle",
    limit: int = 0,
    dry_run: bool = False,
    extract_mode: str = "exchange",
    storage_factory: StorageFactory | None = None,
    extract_kg_proposals: bool = False,
):
    """Mine a conversation file or directory into the palace.

    extract_mode:
        "exchange" — default exchange-pair chunking (Q+A = one unit)
        "general"  — general extractor: decisions, preferences, milestones, problems, emotions
    """

    convo_path = Path(convo_dir).expanduser().resolve()
    if not wing:
        wing_root = convo_path.parent if convo_path.is_file() else convo_path
        wing = resolve_wing_hint(palace_path, convo_path)
        if not wing:
            wing = wing_root.name.lower().replace(" ", "_").replace("-", "_")

    adapter = ConversationExportsAdapter(convo_path)
    items = adapter.scan(limit=limit)
    files = [item.path for item in items]

    print(f"\n{'=' * 55}")
    print("  SwampCastle Mine — Conversations")
    print(f"{'=' * 55}")
    print(f"  Wing:    {wing}")
    print(f"  Source:  {convo_path}")
    print(f"  Files:   {len(files)}")
    print(f"  Palace:  {palace_path}")
    if dry_run:
        print("  DRY RUN — nothing will be filed")
    print(f"{'-' * 55}\n")

    collection = None
    if not dry_run:
        if storage_factory is None:
            settings = CastleSettings(castle_path=palace_path, _env_file=None)
            storage_factory = factory_from_settings(settings)
        collection = storage_factory.open_collection("swampcastle_chests")

    contributor_root = convo_path.parent if convo_path.is_file() else convo_path
    team, registry = _load_contributor_context(contributor_root)

    total_drawers = 0
    files_skipped = 0
    room_counts = defaultdict(int)

    for i, item in enumerate(items, 1):
        filepath = item.path
        source_file = str(filepath)

        # Skip if already filed
        if not dry_run:
            if _file_already_mined(collection, source_file, check_mtime=True):
                files_skipped += 1
                continue
            if _file_already_mined(collection, source_file):
                _purge_source_file(collection, source_file)

        try:
            result = adapter.ingest(
                item,
                palace_path=palace_path,
                convo_path=contributor_root,
                team=team,
                registry=registry,
                extract_mode=extract_mode,
            )
        except (OSError, ValueError):
            continue

        if result is None:
            continue

        chunks = result.chunks
        room = result.room
        contributor = result.contributor
        origin = result.origin
        source_mtime = result.source_mtime

        if dry_run:
            total_drawers += _record_dry_run(result, extract_mode, room_counts)
            continue

        write_origin_manifest(palace_path, origin)

        if extract_mode != "general":
            room_counts[room] += 1

        # File each chunk
        drawers_added = 0
        for chunk in chunks:
            chunk_room = chunk.get("memory_type", room) if extract_mode == "general" else room
            if extract_mode == "general":
                room_counts[chunk_room] += 1
            drawer_id = f"drawer_{wing}_{chunk_room}_{hashlib.sha256((source_file + str(chunk['chunk_index'])).encode()).hexdigest()[:24]}"
            try:
                collection.upsert(
                    documents=[chunk["content"]],
                    ids=[drawer_id],
                    metadatas=[
                        {
                            "wing": wing,
                            "room": chunk_room,
                            "source_file": source_file,
                            "chunk_index": chunk["chunk_index"],
                            "added_by": agent,
                            "filed_at": datetime.now().isoformat(),
                            "ingest_mode": "convos",
                            "extract_mode": extract_mode,
                            **({"source_mtime": source_mtime} if source_mtime is not None else {}),
                            **origin_metadata(origin),
                            **({"contributor": contributor} if contributor else {}),
                        }
                    ],
                )
                drawers_added += 1
            except Exception as e:
                if "already exists" not in str(e).lower():
                    raise

        total_drawers += drawers_added
        print(f"  ✓ [{i:4}/{len(files)}] {filepath.name[:50]:50} +{drawers_added}")

    extracted_candidates = _extract_kg_proposals_if_enabled(
        extract_kg_proposals=extract_kg_proposals,
        dry_run=dry_run,
        storage_factory=storage_factory,
        collection=collection,
        palace_path=palace_path,
        wing=wing,
    )

    print(f"\n{'=' * 55}")
    print("  Done.")
    print(f"  Files processed: {len(files) - files_skipped}")
    print(f"  Files skipped (already filed): {files_skipped}")
    print(f"  Drawers filed: {total_drawers}")
    if extract_kg_proposals:
        if dry_run:
            print("  KG proposal extraction: skipped (dry run)")
        else:
            print(f"  KG candidate triples: {extracted_candidates}")
    if room_counts:
        print("\n  By room:")
        for room, count in sorted(room_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"    {room:20} {count} files")
    print('\n  Next: swampcastle search "what you\'re looking for"')
    print(f"{'=' * 55}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python convo_miner.py <convo_dir> [--palace PATH] [--limit N] [--dry-run]")
        sys.exit(1)

    mine_convos(sys.argv[1], palace_path=CastleSettings(_env_file=None).castle_path)
