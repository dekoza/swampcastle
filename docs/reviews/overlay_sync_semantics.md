# Overlay sync semantics — design note

Date: 2026-05-07
Status: design note
Related docs:
- `docs/sync.md`
- `docs/audit-overlay.md`
- `docs/reviews/memory_audit_overlay_implementation_plan.md`

## Goal

Define how SwampCastle should handle **cross-device synchronization of audit-overlay state** without corrupting the existing memory model.

This is a design note, not an implementation claim.

## Current verified state

Grounded in the current codebase:

### What sync already handles
Verified in:
- `swampcastle/sync.py`
- `swampcastle/sync_client.py`
- `docs/sync.md`

Current sync exchanges:
- drawer records from the active `CollectionStore`
- document text
- metadata
- embeddings when present
- sync metadata (`node_id`, `seq`, `updated_at`)

Conflict resolution today:
- later `updated_at` wins
- on tie, lexicographically higher `node_id` wins

### What the overlay currently stores
Verified in:
- `docs/audit-overlay.md`
- `swampcastle/audit/origin.py`
- `swampcastle/audit/curation.py`
- `swampcastle/audit/derived.py`

Current overlay artifacts:

#### Canonical-enough operational metadata already carried by drawers
- origin fields copied into drawer metadata:
  - `origin_id`
  - `source_kind`
  - `source_platform`
  - `origin_confidence`

#### Local sidecars
- `.swampcastle/origin/<origin-id>.json`
- `.swampcastle/curation/aliases.yaml`
- `.swampcastle/curation/tunnels.yaml`
- `.swampcastle/curation/wings/<wing>.md`
- `.swampcastle/derived/catalog/<wing>.jsonl`
- `.swampcastle/derived/traces/<trace-id>.json`

### Current hard truth
Today:
- drawer metadata syncs
- overlay sidecar files do **not** sync as first-class objects

That is acceptable for:
- origin manifests
- derived artifacts

It is **not** acceptable long-term for:
- human-authored curation (`aliases.yaml`, `tunnels.yaml`, wing notes)

Because those files can contain real operator intent that should survive multi-device use.

---

## What should sync vs what should stay local

## 1. Origin manifests

### Recommendation
Do **not** sync origin manifests as files.

### Why
They are projections of data that is already sufficiently represented elsewhere:
- the stored drawer metadata already carries the query-relevant origin subset
- the manifest file is for audit / inspection, not primary truth

### Rule
- drawer metadata remains authoritative for sync
- origin sidecars are rebuildable local views

## 2. Derived artifacts

### Recommendation
Do **not** sync derived catalog cards or search traces.

### Why
- catalog cards are rebuildable from synced drawers
- search traces are debugging snapshots, not durable product state
- syncing them would create stale, conflicting, low-value churn

### Rule
- derived artifacts stay local-only
- any machine can rebuild them on demand

## 3. Human-authored curation

### Recommendation
This **must** eventually sync.

That includes:
- persona aliases
- people/project aliases if they are curated rather than inferred
- tunnel allow/deny/boost rules
- wing notes

### Why
This is the only overlay category that contains user/operator intent that is not already preserved elsewhere.

If that state stays local forever, multi-device SwampCastle becomes inconsistent by design.

---

## Bad options

These are the tempting but wrong approaches.

## Option A — sync raw sidecar files directly

### Superficial appeal
- easy to explain
- preserves the user's exact files
- no projection layer needed

### Why it is weak
- introduces a second sync substrate unrelated to the current sync engine
- file-level conflict semantics are poor
- YAML / Markdown merges are not safe with naïve last-writer-wins
- you would end up reimplementing a tiny DVCS badly
- platform-specific newline / formatting noise becomes sync noise

### Verdict
Reject as the primary architecture.

It is acceptable only as:
- import/export
- backup
- manual migration aid

## Option B — store curation as normal drawers in the main memory collection

### Superficial appeal
- reuses current sync machinery
- no new store abstraction required

### Why it is wrong
- curation is not memory evidence
- embedding/operator-policy docs pollutes the search corpus
- retrieval semantics become muddy
- a tunnel deny rule is not a memory drawer
- every search / status call becomes more fragile because system state and user evidence share one collection

### Verdict
Reject.

This would be a structural bug, not a shortcut.

## Option C — keep curation local-only forever

### Why it fails
- guarantees cross-device drift
- makes one machine's operator intent invisible on another
- undermines trust in the overlay

### Verdict
Reject as the long-term state.

---

## Recommended model

## Canonical rule

Split overlay state into three sync classes:

| Class | Examples | Sync? | Canonical store |
|---|---|---:|---|
| Drawer-carried metadata | origin fields on drawer metadata | yes | collection records |
| Human-authored curation | aliases, tunnels, wing notes | yes | dedicated overlay store |
| Rebuildable projections | origin sidecars, catalog cards, traces | no | local files only |

That means:
- sync **operator intent**, not file formatting
- rebuild projections locally
- keep evidence and operator policy separate

---

## Recommended architecture for authored curation

## Add a dedicated overlay store

Do not piggyback on the main memory collection.
Do not sync files directly.

Add a dedicated logical store for syncable overlay records.

### Why a dedicated store is the right compromise
It preserves:
- typed sync records
- explicit conflict resolution
- reuse of version-vector style semantics
- separation from semantic search corpus

without pretending YAML/Markdown files are a robust sync substrate.

## Record types

Recommended v1 overlay record families:

### 1. Alias records
Stable key examples:
- `alias/persona/Aurora`
- `alias/person/dek`
- `alias/project/swamp`
- `wing_hint/claude-session`

Payload examples:

```json
{
  "kind": "alias_persona",
  "key": "Aurora",
  "canonical": "Echo",
  "updated_at": "2026-05-07T12:00:00Z",
  "node_id": "laptop-a"
}
```

### 2. Tunnel policy records
Stable key examples:
- `tunnel/allow/auth/personal/proj`
- `tunnel/deny/python/general/swampcastle`
- `tunnel/boost/sync/cognitive_ai/swampcastle`

Payload examples:

```json
{
  "kind": "tunnel_boost",
  "room": "sync",
  "wing_a": "swampcastle",
  "wing_b": "cognitive_ai",
  "weight": 0.15,
  "updated_at": "2026-05-07T12:00:00Z",
  "node_id": "laptop-a"
}
```

### 3. Wing note records
Do **not** sync raw markdown blobs if you can avoid it.

Preferred model:
- sync a structured note document per wing
- keep sections explicit

Example key:
- `wing_note/swampcastle`

Payload example:

```json
{
  "kind": "wing_note",
  "wing": "swampcastle",
  "sections": {
    "Pinned context": ["v4 uses Castle + services."],
    "Open threads": ["refine tunnel policy"],
    "Stale assumptions": ["files alone are enough"]
  },
  "updated_at": "2026-05-07T12:00:00Z",
  "node_id": "laptop-a"
}
```

The local markdown file becomes a projection of this structured record, not the sync object itself.

---

## Conflict semantics

This is where bad designs die.

## Aliases and tunnel rules

### Recommendation
Use record-level last-writer-wins.

Why this is acceptable:
- each alias/tunnel rule is a small keyed object
- concurrent edits to the same exact key are rare
- semantics are atomic enough for LWW to be understandable

## Wing notes

Naïve LWW on the full note body is too lossy.

### Recommendation
Use structured note payloads plus conflict capture.

Specifically:
- the primary record still resolves with LWW for the main key
- if both sides edited the same wing note concurrently and payloads differ, store the losing payload as a **conflict artifact** for manual review

Example conflict key:
- `wing_note_conflict/swampcastle/<timestamp>/<node_id>`

That gives you:
- deterministic sync
- no silent destruction of the losing edit
- a clear manual repair path

This is better than pretending markdown line merges are safe inside a custom sync engine.

---

## File projection rules

Once authored curation becomes syncable, local files should be treated as **projections and edit surfaces**, not primary sync objects.

### Recommended rule

#### Import direction
- local file edits can be imported into the overlay store explicitly
- or watched/imported automatically later if you really need it

#### Export direction
- synced overlay store can regenerate:
  - `aliases.yaml`
  - `tunnels.yaml`
  - `wings/<wing>.md`

### Initial recommendation
Keep it simple at first:
- explicit import/export commands
- no background file watchers

Suggested future CLI:
- `swampcastle curation import`
- `swampcastle curation export`

Do not build filesystem watch daemons until there is a real user need.

---

## How this should fit the current sync engine

## Short-term
Do not mutate the existing drawer sync path just to cram overlay files into it.

## Medium-term recommendation
Extend sync into a multi-store protocol.

Conceptually:
- store A = drawer collection
- store B = overlay record store

Each store maintains:
- its own version vector or namespace inside one version vector file
- its own change extraction / apply logic
- its own conflict semantics

### Why not one shared flat version vector with no namespace?
Because drawer records and overlay records are different domains.
Namespace them explicitly.

Suggested VV shape:

```json
{
  "drawers": {"node-a": 120, "node-b": 88},
  "overlay": {"node-a": 14, "node-b": 7}
}
```

That is clearer and safer than pretending everything is one homogeneous stream.

---

## Migration plan

## Phase 0 — current state
- drawer metadata syncs
- origin manifests local-only
- curation local-only
- derived artifacts local-only

## Phase 1 — codify current behavior clearly
- document that sidecars are local-only today
- do not imply authored curation sync already exists

## Phase 2 — add an internal overlay record store
- local persistence only first
- no network sync yet
- import/export from local files

## Phase 3 — add overlay sync to protocol
- namespace version vectors
- push/pull overlay changes alongside drawer changes
- implement conflict artifact handling for wing notes

## Phase 4 — optional polish
- explicit review UI/CLI for wing-note conflicts
- optional automatic export back to local sidecar files
- maybe MCP read-only access to conflict artifacts

---

## Highest-risk mistakes

1. **Syncing raw markdown/yaml files as the canonical network payload.**
   That is easy to start and ugly to maintain.

2. **Stuffing curation into the main memory collection.**
   That pollutes retrieval semantics.

3. **Using plain LWW for whole wing-note markdown bodies with no conflict capture.**
   That silently destroys user-authored content.

4. **Syncing derived traces/catalogs.**
   That creates low-value churn and stale state.

---

## Bottom line

Recommended semantics:

- **sync drawer-carried origin metadata** because it already rides on canonical records
- **do not sync origin sidecar files**
- **do not sync derived catalog cards or search traces**
- **do sync authored curation**, but through a dedicated structured overlay store
- **treat local YAML/Markdown as projections/edit surfaces**, not the sync payload
- **namespace overlay sync separately from drawer sync**
- **capture conflicts for wing notes instead of silently overwriting them**

That is the least bad architecture.
Anything simpler either loses data or pollutes the core memory model.
