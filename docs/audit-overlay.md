# Audit overlay

SwampCastle's canonical memory is still:

- verbatim drawers in the collection store
- accepted knowledge-graph facts in the graph store
- proposal-first extracted facts in the candidate store

The **audit overlay** is an additive layer that makes some parts of that memory easier to inspect and debug.

Current shipped scope:
- source-origin manifests for conversation ingest
- hook-driven transcript auto-ingest
- explainable search output

Not shipped yet:
- human-editable alias / tunnel / wing-note curation files
- rebuildable derived catalogs or trace files beyond inline search explanation
- sync of overlay sidecars across devices

## 1. Source-origin manifests

Conversation ingest now detects a small source-origin profile for each ingested transcript.

Current fields include:
- `origin_id`
- `source_kind`
- `platform`
- `declared_transformations`
- `confidence`
- `source_file`
- `updated_at`

The full manifest is written to:

```text
<castle_path>/.swampcastle/origin/<origin-id>.json
```

The query-relevant subset is also copied into drawer metadata so search and sync do not depend on the sidecar file alone.

Current drawer metadata fields added by conversation ingest:
- `origin_id`
- `source_kind`
- `source_platform`
- `origin_confidence`

## 2. What origin detection currently recognizes

The current implementation is intentionally local and conservative.

Recognized platforms:
- Claude Code JSONL → `claude-code`
- Codex JSONL → `codex`
- Claude export JSON → `claude-ai`
- ChatGPT export JSON → `chatgpt`
- Slack export JSON → `slack`

Declared transformations currently reported:
- `jsonl_normalize`
- `json_normalize`

Plain-text transcripts may still be filed as conversation exports without a specific platform label.

## 3. Hook-driven transcript auto-ingest

The hooks in `swampcastle.hooks_cli` now ingest the active `transcript_path` automatically.

### stop hook
When the save interval fires:
- the hook counts human messages
- if the active transcript path is present and readable, it starts a background ingest for that transcript in `--mode convos`
- it still blocks and asks the assistant to save key context explicitly

### precompact hook
Before compaction:
- the hook runs transcript ingest synchronously for the active `transcript_path`
- then it blocks with the normal precompact save instruction

### Legacy additive behavior
The legacy `MEMPAL_DIR` environment variable is still supported.
If it is set, hooks also ingest that directory.
It is **additive** to transcript auto-ingest, not a replacement for it.

## 4. Conversation ingest behavior for active transcripts

Conversation ingest now supports:
- a directory of conversation exports
- a single transcript file path

For conversation files, SwampCastle stores `source_mtime` metadata and treats a changed transcript as a refresh signal:
- unchanged transcript → skipped
- changed transcript → old drawers for that `source_file` are removed, then the transcript is re-ingested

This is what makes repeated hook-driven ingest safe for growing local transcripts.

## 5. Explainable search

`SearchQuery` now supports:
- `lexical_rerank`
- `hybrid`
- `explain`

CLI examples:

```bash
swampcastle seek "auth migration"
swampcastle seek "auth migration clerk" --lexical-rerank --explain
swampcastle seek "auth migration clerk" --hybrid --explain
```

When `explain=true`, search hits may include:
- `matched_via` — `dense`, `lexical`, or `hybrid`
- `dense_similarity`
- `lexical_score`
- `boosts`
- `origin_id`
- `source_kind`
- `source_platform`

The CLI prints those explanation fields only when `--explain` is requested.

## 6. Canonical vs overlay data

This distinction matters.

### Canonical
- drawers
- accepted KG facts
- accepted proposal reviews once written into the KG

### Overlay / audit
- source-origin manifest sidecars
- inline explanation metadata derived at query time
- hook log files

If you delete the origin sidecar directory, you lose an audit surface, not the verbatim memory itself.
The stored drawers remain the evidence source of truth.

## 7. Sync caveat

Current sync is still collection-centered.

That means:
- drawer metadata carrying origin fields syncs
- origin manifest sidecar files are local audit artifacts and are not currently synced as first-class objects

If two machines need the same sidecar manifests, rebuild them locally from the synced drawer metadata or re-run ingest on that machine.

## 8. Future overlay work

Planned but not yet shipped:
- human-editable `aliases.yaml`
- human-editable `tunnels.yaml`
- per-wing curated notes
- derived catalog cards / trace files
- explicit overlay sync semantics

Until those exist, this document only describes the currently shipped Wave 1 behavior.
