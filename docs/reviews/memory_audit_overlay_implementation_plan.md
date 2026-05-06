# Memory Audit Overlay — Concrete Implementation Plan

Date: 2026-05-07
Status: implementation plan
Related docs:
- `docs/architecture.md`
- `docs/configuration.md`
- `docs/getting-started.md`
- `docs/hooks.md`
- `docs/mining.md`
- `docs/searching.md`
- `docs/mcp.md`
- `docs/reviews/kg_auto_extraction_implementation_plan.md`

## Goal

Build a **memory audit overlay** for SwampCastle that improves:

- source provenance
- transcript capture reliability
- manual tuning / auditability
- search explainability

without replacing the current canonical storage model:

- verbatim drawers in the collection store
- accepted KG facts in the graph store
- proposal-first extracted facts in the proposal layer

This is not a SharedBrain rewrite. It is a controlled overlay on top of the current SwampCastle architecture.

---

## Current verified starting point

The plan below is grounded in the current repository state.

### Search

Verified in:
- `swampcastle/models/drawer.py`
- `swampcastle/services/search.py`
- `swampcastle/retrieval/hybrid.py`
- `docs/searching.md`

Current state:
- `SearchQuery` already supports `lexical_rerank` and `hybrid`.
- `SearchHit` currently returns only:
  - `text`
  - `wing`
  - `room`
  - `similarity`
  - `source_file`
  - `contributor`
- `SearchService` can do dense-only, dense+lexical rerank, or lightweight hybrid retrieval.
- CLI `seek` does **not** currently expose `lexical_rerank`, `hybrid`, or search explanation flags.

### Hooks

Verified in:
- `swampcastle/hooks_cli.py`
- `docs/hooks.md`

Current state:
- stop / precompact hooks block and tell the assistant to save.
- hooks only auto-ingest the legacy `MEMPAL_DIR` directory.
- hooks do **not** auto-ingest the active `transcript_path`.

### Conversation ingest

Verified in:
- `swampcastle/mining/convo.py`
- `swampcastle/mining/normalize.py`
- `docs/mining.md`

Current state:
- conversation mining normalizes multiple transcript formats.
- conversation mining skips a file if `source_file` already exists.
- unlike project mining, conversation mining does **not** currently track `source_mtime` for incremental re-ingest.
- this means active transcripts are a bad fit for naive repeated hook-driven re-ingest.

### Existing human-editable state

Verified in:
- `docs/configuration.md`
- `swampcastle/entity_registry.py`

Current state:
- `~/.swampcastle/entity_registry.json` already exists as a user-editable identity registry.
- there is no castle-scoped curation overlay for aliases, tunnel policy, or curated wing notes.
- there is no source-origin manifest layer.

### Architecture boundary

Verified in:
- `docs/architecture.md`
- `swampcastle/castle.py`
- `swampcastle/mcp/tools.py`

Current state:
- `Castle` exposes `catalog`, `search`, `graph`, `vault`, and `kg_proposals` services.
- the MCP server currently exposes 19 tools.
- current sync behavior is centered on collection records, not arbitrary sidecar files.

---

## Non-goals for v1

These are explicitly out of scope for the first implementation wave.

- replacing drawers with markdown summaries
- adding a global `MEMORY.md` as canonical memory
- auto-writing curated notes into the accepted KG
- building a full external plugin ecosystem for source adapters on day one
- syncing arbitrary overlay sidecar files across devices in v1
- adding LLM-dependent origin detection by default
- shipping a large new MCP tool surface before the model and file layout are proven

If any of these creep into v1, the scope is wrong.

---

## Design decisions

## 1. Canonical storage does not move

The canonical sources of truth remain:

- **drawers** for verbatim evidence
- **accepted KG facts** for structured truth
- **proposal store** for extraction candidates

The audit overlay can annotate, explain, and guide. It does not replace those layers.

## 2. Overlay files are sparse and scoped

Do not recreate SharedBrain's failure mode by accumulating one giant prose memory file.

The human-editable layer must stay small and structured:

- aliases / personas
- tunnel allow/deny/boost rules
- short per-wing curated notes

## 3. Derived artifacts are rebuildable

Any catalog, trace, or sidecar derived from stored memory must be rebuildable.

That means:
- no hidden second database
- no derived artifact as the only copy of important information
- no silent search behavior driven by non-inspectable generated state

## 4. Explainability is a feature, not a debug-only afterthought

Search results should be able to say:
- whether they matched via dense, lexical, or hybrid paths
- what scores or boosts mattered
- what source/origin metadata was attached

## 5. Sync safety beats aesthetic purity

Because SwampCastle sync is collection-centered, origin metadata that matters at query time should live on drawer metadata, not only in sidecar files.

Sidecar manifests are for human inspection and local audit.
They are not the only copy of operationally-relevant origin data.

---

## Proposed overlay model

The overlay has three layers.

| Layer | Purpose | Canonical | Human-editable | Rebuildable |
|---|---|---:|---:|---:|
| Source-origin metadata | source kind, platform, persona hints, provenance | stored on drawer metadata | partly via curation overrides | yes |
| Curation overlay | aliases, tunnel policy, wing notes | no | yes | no |
| Derived audit artifacts | catalog cards, search traces, summaries | no | usually no | yes |

---

## Proposed storage layout

### Existing verified anchors

- `~/.swampcastle/config.json`
- `~/.swampcastle/entity_registry.json`
- `<castle_path>/version_vector.json`
- `<castle_path>/.swampcastle/*.embedder.json`

### Proposed additive layout

```text
<castle_path>/
  <existing backend data>
  version_vector.json
  .swampcastle/
    *.embedder.json
    origin/
      <origin-id>.json
    curation/
      aliases.yaml
      tunnels.yaml
      wings/
        <wing>.md
    derived/
      catalog/
        <wing>.jsonl
      traces/
        <trace-id>.json
```

### Intent of each path

#### `.swampcastle/origin/<origin-id>.json`
Human-readable source-origin manifest.

This file is **not** the only copy of origin data.
The fields needed for search / sync must also be written into drawer metadata.

#### `.swampcastle/curation/aliases.yaml`
Human overrides for:
- agent persona names
- person aliases
- project aliases
- optional wing alias hints

#### `.swampcastle/curation/tunnels.yaml`
Human policy for cross-wing inference:
- allow
- deny
- optional boost

#### `.swampcastle/curation/wings/<wing>.md`
Short curated wing note.

Expected sections:
- `Pinned context`
- `Open threads`
- `Stale assumptions`

#### `.swampcastle/derived/catalog/<wing>.jsonl`
Rebuildable compact retrieval aids. Not canonical.

#### `.swampcastle/derived/traces/<trace-id>.json`
Optional explain-mode trace dumps for debugging or benchmark review.

---

## Wave plan

## Wave 1 — reliable transcript capture + source-origin manifests + explainable search

This is the minimum wave worth shipping.

### 1A. Add source-origin model and persistence

#### Goal
Attach inspectable source provenance to ingested conversation material.

#### New files
- `swampcastle/models/origin.py`
- `swampcastle/audit/__init__.py`
- `swampcastle/audit/origin.py`

#### Modified files
- `swampcastle/models/__init__.py`
- `swampcastle/mining/convo.py`
- `swampcastle/mining/normalize.py`
- `swampcastle/hooks_cli.py`
- `swampcastle/settings.py` only if a computed helper path is needed

#### Proposed data model

```python
class SourceOrigin(BaseModel):
    schema_version: int = 1
    origin_id: str
    source_kind: Literal["project_file", "conversation_export", "mixed", "unknown"]
    platform: str | None = None
    user_name: str | None = None
    agent_personas: list[str] = []
    declared_transformations: list[str] = []
    confidence: Literal["heuristic", "curated"] = "heuristic"
    source_file: str | None = None
    updated_at: str
```

#### Detection policy for v1

Keep v1 local and deterministic.

Allowed signals:
- transcript file extension / structure
- JSONL event shape
- known export schema signatures from `swampcastle/mining/normalize.py`
- curation alias overrides from `aliases.yaml`

Do **not** add remote LLM origin detection in v1.
If an LLM-assisted refinement layer is added later, it must be opt-in and consent-gated.

#### Where origin data lives

Store the minimal operational fields on drawer metadata:
- `origin_id`
- `source_kind`
- `source_platform`
- `origin_confidence`

Write the full manifest to:
- `<castle_path>/.swampcastle/origin/<origin-id>.json`

#### Important constraint

The manifest must be reproducible from stored fields plus local detection inputs.
It must not become the only place where search-relevant origin facts live.

### 1B. Fix active transcript ingest before enabling hook auto-ingest

#### Problem
Current conversation ingest skips a transcript after the first ingest because it only checks `source_file` existence.
That is incompatible with active transcript capture.

#### Required change
Before hook-driven transcript auto-ingest ships, conversation ingest must gain one of these behaviors:

### Option A — mtime-aware full-file reingest
- store `source_mtime` on convo drawer metadata
- if file changed, delete existing drawers for that `source_file`
- re-normalize and re-file the whole transcript

### Option B — transcript sweeper
- keep file-level ingest for backfill
- add message-level incremental ingest for active transcripts
- key progress by session/transcript cursor

#### Recommendation
Use **Option A in Wave 1** because it is smaller and easier to verify.
Plan **Option B** as Wave 3 if repeated full-file reingest proves too expensive.

#### New helper behavior needed
Collection backends only support `delete(ids=[...])`, not `delete(where=...)`.
So the reingest path must:
- `get(where={"source_file": ...})`
- collect ids
- delete those ids explicitly
- then re-upsert the refreshed transcript drawers

#### Modified files
- `swampcastle/mining/convo.py`
- possibly shared helper extraction in `swampcastle/mining/*`
- tests covering unchanged transcript vs changed transcript behavior

### 1C. Hook-driven active transcript ingest

#### Goal
When `transcript_path` is present, hooks should ingest the active transcript instead of only blocking and asking the assistant to remember.

#### Modified files
- `swampcastle/hooks_cli.py`
- `tests/test_hooks_cli.py`

#### Proposed behavior

### stop hook
When the save interval fires:
1. count human messages as it does now
2. if `transcript_path` exists, enqueue background conversation ingest for that file or its containing session directory
3. keep the current block response
4. preserve `MEMPAL_DIR` as additive legacy behavior, not a replacement

### precompact hook
When precompact fires:
1. if `transcript_path` exists, run transcript ingest synchronously with timeout
2. then block with the current precompact reason

#### Guardrails
- if `transcript_path` is missing or unreadable, keep current behavior
- log transcript-ingest attempts and failures into `hook.log`
- do not ingest project files unless `MEMPAL_DIR` is explicitly set
- do not guess a wing from unrelated paths when explicit config exists

### 1D. Explainable search surface

#### Goal
Expose why a result matched.

#### New / modified files
- `swampcastle/models/drawer.py`
- `swampcastle/services/search.py`
- `swampcastle/retrieval/hybrid.py`
- `swampcastle/cli/commands.py`
- `swampcastle/cli/main.py`
- `swampcastle/mcp/tools.py` (schema auto-picks up model changes, but descriptions should be updated)

#### Proposed request model change

Add to `SearchQuery`:

```python
explain: bool = Field(
    default=False,
    description="Include explanation metadata about how each hit was ranked",
)
```

Also expose existing retrieval modes on the CLI:
- `--lexical-rerank`
- `--hybrid`
- `--explain`

#### Proposed response model change

Extend `SearchHit` with optional fields:

```python
matched_via: Literal["dense", "lexical", "hybrid"] | None = None
dense_similarity: float | None = None
lexical_score: float | None = None
boosts: list[str] = []
origin_id: str | None = None
source_kind: str | None = None
source_platform: str | None = None
```

#### Initial explanation policy

If `explain=false`, return current lean behavior.
If `explain=true`, include:
- retrieval path
- dense similarity
- lexical score when rerank/hybrid is used
- origin metadata copied from drawer metadata

Do **not** write trace files in Wave 1.
Keep explanation output inline first.

### Wave 1 acceptance criteria

#### Unit tests
- origin detection for Claude Code JSONL
- origin detection for Codex JSONL
- origin manifest round-trip serialization
- conversation ingest stores `source_mtime` and origin metadata
- changed transcript reingests, unchanged transcript skips
- search explain output for dense-only
- search explain output for lexical rerank
- search explain output for hybrid

#### Integration tests
- mine conversation export -> origin manifest written -> search hit returns origin metadata
- hook stop with valid `transcript_path` triggers transcript ingest path
- hook precompact with valid `transcript_path` runs synchronous ingest path
- active transcript grows -> second ingest refreshes searchable content instead of skipping forever

#### E2E / CLI tests
- `swampcastle seek "..." --explain`
- `swampcastle seek "..." --hybrid --explain`
- CLI output remains readable when explanation is omitted

---

## Wave 2 — human-editable curation overlay

This is where SwampCastle takes the best part of SharedBrain without inheriting its weaknesses.

### 2A. Alias / persona overrides

#### Goal
Let users correct identity/persona routing with plain files.

#### New files
- `swampcastle/audit/curation.py`

#### Modified files
- `swampcastle/audit/origin.py`
- `swampcastle/entity_registry.py` only if integration is warranted
- `swampcastle/mining/convo.py`
- `swampcastle/services/search.py` if explanation should surface applied alias overrides

#### Proposed file
`<castle_path>/.swampcastle/curation/aliases.yaml`

#### Initial supported sections

```yaml
personas:
  Claude:
    type: agent_persona
  Codex:
    type: agent_persona

people:
  dekoza:
    canonical: Dominik

projects:
  swamp:
    canonical: swampcastle

wing_hints:
  claude_code_sessions: swampcastle
```

#### Rules
- keep the schema conservative
- do not try to build a generalized ontology editor
- invalid yaml or invalid keys must fail clearly

### 2B. Wing notes

#### Goal
Provide a human-readable curation surface that stays small.

#### Proposed file
`<castle_path>/.swampcastle/curation/wings/<wing>.md`

#### Expected template

```md
# <wing>

## Pinned context
- ...

## Open threads
- ...

## Stale assumptions
- ...
```

#### Initial use in v2
- not used for ranking
- not embedded by default
- surfaced later via startup packs / explicit reads

That constraint is important. If wing notes start influencing retrieval invisibly, the system becomes muddy.

### 2C. Tunnel policy overlay

#### Goal
Let users suppress or bless cross-wing links explicitly.

#### Proposed file
`<castle_path>/.swampcastle/curation/tunnels.yaml`

#### Proposed schema

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

#### Initial use in v2
- used only by graph traversal / tunnel discovery surfaces
- not applied to normal search ranking in the same wave unless benchmarked

### Wave 2 acceptance criteria

#### Unit tests
- alias file load / validation
- tunnel policy load / validation
- alias override precedence over heuristic origin detection
- wing note discovery and template parsing

#### Integration tests
- alias override changes detected persona classification
- denied tunnel does not appear in tunnel listing
- allowed tunnel appears even when heuristic inference would not add it

#### E2E / CLI tests
- explicit commands or status views used to inspect loaded curation files
- malformed curation file gives a clear error, not silent ignore

---

## Wave 3 — rebuildable derived audit artifacts

Do not start here. This wave only makes sense after Waves 1 and 2 are proven.

### 3A. Catalog cards

#### Goal
Create a compact, inspectable retrieval aid that can later replace the current brute-force sparse scan.

#### Proposed file
`<castle_path>/.swampcastle/derived/catalog/<wing>.jsonl`

#### Record shape

```json
{
  "wing": "swampcastle",
  "room": "search",
  "topic": "hybrid retrieval",
  "entities": ["LanceDB", "BM25"],
  "drawer_ids": ["drawer_...", "drawer_..."],
  "source_files": ["/path/to/file.py"]
}
```

#### Rules
- rebuildable from stored drawers
- never canonical
- never the only copy of topic/entity linkage

### 3B. Search traces

#### Goal
When `--explain` is not enough, optionally persist a trace for debugging or retrieval benchmarking.

#### Proposed file
`<castle_path>/.swampcastle/derived/traces/<trace-id>.json`

#### Use cases
- benchmark regressions
- explain-mode snapshots in tests
- debugging tunnel / lexical / dense interactions

### 3C. Transcript sweeper

If Wave 1 full-file reingest proves too expensive or too noisy, add a message-level sweeper.

#### Goal
Incrementally ingest only new transcript events without reprocessing the full file each time.

#### Constraint
This should be introduced only after there is real evidence that Wave 1's simpler reingest path is insufficient.

### Wave 3 acceptance criteria

#### Unit tests
- catalog rebuild idempotence
- catalog lines remain stable under drawer reorder
- trace file schema validation
- sweeper cursor logic if implemented

#### Integration tests
- rebuild derived catalog after fresh gather
- explain-mode trace matches actual returned search ordering
- re-running rebuild does not duplicate artifacts

---

## Wave 4 — internal source adapter seam

This wave is architectural cleanup, not the first shipping milestone.

### Goal
Stop growing `mine` and `convo` as special cases forever.

### New internal package
- `swampcastle/mining/adapters/__init__.py`
- `swampcastle/mining/adapters/base.py`
- `swampcastle/mining/adapters/project_files.py`
- `swampcastle/mining/adapters/conversation_exports.py`

### Initial contract
Keep this internal first.
Do not promise third-party plugin support yet.

#### Proposed shape

```python
class BaseSourceAdapter(ABC):
    name: str
    declared_transformations: tuple[str, ...] = ()

    @abstractmethod
    def scan(self, source: Path) -> list[SourceItem]:
        ...

    @abstractmethod
    def ingest(self, item: SourceItem, *, castle: Castle) -> IngestResult:
        ...
```

### Why internal-only first
The external plugin story is not free.
It carries:
- compatibility burden
- schema burden
- documentation burden
- testing burden

SwampCastle should prove the internal seam first.

### Wave 4 acceptance criteria
- existing `gather` CLI still works unchanged
- project and conversation ingest both go through adapter objects internally
- adapter transformation declarations are visible in code and tests

---

## Public CLI and MCP plan

## CLI additions

### Wave 1
Add to `seek`:
- `--lexical-rerank`
- `--hybrid`
- `--explain`

Do **not** add a large new command tree in the first wave.

### Possible later additions
Only after the underlying files and schemas are stable:
- `swampcastle origin show <source-file>`
- `swampcastle curation check`
- `swampcastle derived rebuild`

## MCP changes

### Wave 1
Keep the tool surface small.

Use the existing `search` tool and extend its schema with:
- `explain`

Use additive response fields on hits instead of new tools.

### Later
Consider new MCP read-only tools only if the overlay is already stable locally:
- `get_origin`
- `get_curation`
- `rebuild_derived_catalog`

Do not add MCP write tools for curation files in the same wave that introduces the local file format.
That is a recipe for schema churn.

---

## Sync implications

This is the highest-risk design area.

## v1 rule

### Source-origin metadata
Store the query-relevant subset on drawer metadata so sync carries it.

### Origin manifest sidecars
Treat them as local audit artifacts that can be rebuilt.

### Curation overlay
Treat as local-only in v1.
Document that clearly.

### Derived artifacts
Treat as rebuildable local artifacts.
Do not sync them in v1.

## Deferred sync work
If cross-device curation becomes necessary later, choose one of these explicitly:
- sync curation files through a dedicated sync payload
- mirror curated state into a reserved synced collection/table

Do not smuggle local-only curation behavior into sync implicitly.

---

## Test strategy

This project is not a web app, so the required testing pyramid here is:

## Unit
For:
- origin detection
- manifest persistence
- curation file validation
- transcript reingest logic
- explain-mode search fields
- tunnel policy evaluation

## Integration
For:
- gather + conversation ingest + search round trip
- hook input -> transcript ingest path -> searchable drawers
- origin metadata surviving storage round trip
- curation overrides affecting ingest / traversal behavior

## E2E / CLI
For:
- `seek --explain`
- hook command invocation through `run_hook`
- end-to-end conversation ingest from sample exports

## Regression
For:
- retrieval result ordering when `explain=false`
- hybrid retrieval behavior before and after explanation fields are added
- backward compatibility of MCP `search` responses for clients that ignore new fields

---

## Documentation update plan

Do **not** update public docs early and pretend the feature exists.
The current documentation should remain honest until corresponding code lands.

## Documentation wave 0 — now

This implementation plan file is the only documentation change that should land before code.

Added file:
- `docs/reviews/memory_audit_overlay_implementation_plan.md`

## Documentation wave 1 — after transcript ingest + origin manifests + explainable search land

### New doc
- `docs/audit-overlay.md`

### Purpose of new doc
Explain:
- what the audit overlay is
- what is canonical vs derived
- where origin manifests live
- what `seek --explain` returns
- current sync caveats

### Existing docs to update

#### `docs/architecture.md`
Add a short subsection describing the audit overlay boundary:
- origin metadata
- curation overlay
- derived artifacts

#### `docs/configuration.md`
Document:
- computed overlay paths under `<castle_path>/.swampcastle/`
- any new helper settings or env vars if introduced
- explicit note that curation is local-only in v1

#### `docs/getting-started.md`
Add:
- transcript auto-ingest note in the hooks section or conversation ingest section
- `seek --explain` example
- pointer to `docs/audit-overlay.md`

#### `docs/hooks.md`
Update honestly:
- hooks ingest the active `transcript_path`
- `MEMPAL_DIR` remains additive legacy behavior
- transcript ingest timing / timeout behavior

#### `docs/mining.md`
Document:
- source-origin manifest generation during conversation ingest
- transcript reingest behavior for growing transcript files

#### `docs/searching.md`
Document:
- `SearchQuery.explain`
- explanation fields on hits
- CLI flags `--lexical-rerank`, `--hybrid`, `--explain`

#### `docs/cli.md`
Update:
- new `seek` flags
- any origin / audit-related read-only commands if they land

#### `docs/mcp.md`
Update:
- `search` request schema now includes `explain`
- returned hit objects may contain explanation and origin fields

#### `CHANGELOG.md`
Add release note entries only for shipped behavior.
Do not document deferred waves as if they landed.

### Optional top-level docs
Update these only if the feature is stable enough to advertise broadly:
- `README.md`
- `docs/releases/<current-release>.md`

Rule: do not put audit overlay in the headline README until at least Wave 1 is merged and tested.

## Documentation wave 2 — after curation overlay lands

### `docs/audit-overlay.md`
Expand with:
- `aliases.yaml`
- `tunnels.yaml`
- wing note conventions
- local-only sync caveat

### Existing docs to update
- `docs/architecture.md`
- `docs/configuration.md`
- `docs/mcp.md` only if new read-only tools land
- `docs/cli.md` only if new inspection commands land

## Documentation wave 3 — after derived catalog / traces land

### `docs/audit-overlay.md`
Expand with:
- derived catalog cards
- explain trace files
- rebuild behavior

### Possible new doc
Only if the surface grows enough to justify it:
- `docs/retrieval-debugging.md`

## Documentation wave 4 — after internal adapters are proven

Only then consider a new doc such as:
- `docs/mining-adapters.md`

Do not create this doc before the internal seam is real.

---

## Recommended execution order

### Wave 1
- add origin model and manifest persistence
- make conversation ingest safe for growing transcripts
- hook-driven transcript ingest
- explainable search surface
- update public docs for shipped behavior

### Wave 2
- aliases.yaml
- tunnel policy overlay
- per-wing notes
- update `docs/audit-overlay.md` and related docs

### Wave 3
- derived catalog cards
- optional explain trace files
- transcript sweeper only if necessary
- documentation expansion

### Wave 4
- internal adapter seam
- documentation for internal architecture only after it exists

---

## Bottom line

The right path is:

- keep drawers and KG canonical
- add origin metadata as an additive layer
- fix transcript ingest reliability before enabling hook auto-ingest
- add explainable search through the existing `search` surface
- add small human-editable curation files, not a giant markdown brain
- keep derived artifacts rebuildable
- update public docs only after each wave is real

That gives SwampCastle the best lessons from MemPalace and SharedBrain without inheriting the worst failure modes of either.
