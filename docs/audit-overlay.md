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
- human-editable local curation files for aliases, tunnel policy, and wing notes
- rebuildable derived catalog cards under `<castle_path>/.swampcastle/derived/catalog/`
- optional saved search traces under `<castle_path>/.swampcastle/derived/traces/`
- read-only CLI inspection / rebuild entry points:
  - `swampcastle curation check`
  - `swampcastle derived rebuild`
- read-only MCP audit tools:
  - `get_origin`
  - `get_curation`
  - `list_catalog_cards`

Not shipped yet:
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

## 6. Local curation files

The audit overlay now includes human-editable curation files under:

```text
<castle_path>/.swampcastle/curation/
```

Current files:
- `aliases.yaml`
- `tunnels.yaml`
- `wings/<wing>.md`

### `aliases.yaml`

Current supported sections:
- `personas`
- `people`
- `projects`
- `wing_hints`

Example:

```yaml
personas:
  Aurora:
    canonical: Echo

people:
  dek:
    canonical: Dominik

projects:
  swamp:
    canonical: swampcastle

wing_hints:
  claude-session: swampcastle
```

Current shipped behavior:
- persona aliases can override heuristic `agent_personas` detection in source-origin manifests
- `wing_hints` can override the default wing chosen by conversation ingest when `--wing` is omitted

### `tunnels.yaml`

Current supported sections:
- `allow`
- `deny`
- `boost`

Example:

```yaml
allow:
  - wing_a: swampcastle
    wing_b: cognitive_ai
    room: embeddings

deny:
  - wing_a: swampcastle
    wing_b: general
    room: python

boost:
  - wing_a: swampcastle
    wing_b: cognitive_ai
    room: sync
    weight: 0.15
```

Current shipped behavior:
- denied tunnel pairs are hidden from `find_tunnels()`
- allowed tunnel pairs can appear even when the raw overlap graph would not infer them
- boost rules are attached as ordering hints for tunnel listings

### `wings/<wing>.md`

Wing notes are small local curation documents.

Required sections:
- `Pinned context`
- `Open threads`
- `Stale assumptions`

Example:

```md
# swampcastle

## Pinned context
- v4 uses Castle + services.

## Open threads
- refine tunnel policy.

## Stale assumptions
- files alone are enough.
```

Wing notes are currently:
- validated by the loader
- discoverable through `swampcastle curation check`
- **not** used for ranking or automatic retrieval

## 7. Inspecting local curation

Use:

```bash
swampcastle curation check
swampcastle curation check --wing swampcastle
```

This command validates the local curation files and prints a compact summary.
Malformed YAML or malformed wing-note structure fails clearly instead of being ignored.

The same local state is also readable through MCP via `get_curation`.

## 8. Derived artifacts

Derived artifacts live under:

```text
<castle_path>/.swampcastle/derived/
```

Current shipped paths:
- `catalog/<wing>.jsonl`
- `traces/<trace-id>.json`

### Catalog cards

Catalog cards are rebuildable JSONL records grouped per wing.
Each card currently contains:
- `wing`
- `room`
- `topic`
- `entities`
- `drawer_ids`
- `source_files`

Use:

```bash
swampcastle derived rebuild
swampcastle derived rebuild --wing swampcastle
```

Current behavior:
- rebuilds one catalog file per wing
- removes stale catalog files on full rebuild
- keeps card ordering stable across drawer reorderings
- does **not** currently change live search ranking by itself

### Search traces

You can persist a local search trace from the CLI with:

```bash
swampcastle seek "auth migration clerk" --hybrid --write-trace
```

`--write-trace` implies explain-mode data in the saved trace even if you did not also ask the CLI to print explanation lines inline.

Current trace payload includes:
- `request`
- `response`
- `trace_id`
- `created_at`

These traces are for debugging and benchmarking snapshots. They are not canonical memory.

Current MCP support for derived artifacts is limited to catalog-card inspection via `list_catalog_cards`. Search traces remain a local CLI/debug surface for now.

## 9. Canonical vs overlay data

This distinction matters.

### Canonical
- drawers
- accepted KG facts
- accepted proposal reviews once written into the KG

### Overlay / audit
- source-origin manifest sidecars
- local curation files (`aliases.yaml`, `tunnels.yaml`, wing notes)
- inline explanation metadata derived at query time
- hook log files

If you delete the origin sidecar directory, you lose an audit surface, not the verbatim memory itself.
The stored drawers remain the evidence source of truth.

## 10. Sync caveat

Current sync is still collection-centered.

That means:
- drawer metadata carrying origin fields syncs
- origin manifest sidecar files are local audit artifacts and are not currently synced as first-class objects

If two machines need the same sidecar manifests, rebuild them locally from the synced drawer metadata or re-run ingest on that machine.

## 11. Future overlay work

Planned but not yet shipped:
- explicit overlay sync semantics
- MCP read surfaces for curation and overlay inspection
- richer curation influence over retrieval beyond current origin / tunnel hooks
- transcript sweeper / message-level incremental capture if full-file refresh proves insufficient

This document describes the currently shipped Wave 1 + Wave 2 + Wave 3 behavior.
