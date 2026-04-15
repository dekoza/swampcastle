# KG Auto-Extraction Pipeline — Design Note

Date: 2026-04-14
Status: proposed design, not implemented

## Executive summary

SwampCastle should **not** auto-write extracted facts directly into the knowledge graph during ingest.
That would optimize for speed over correctness and would poison the KG with:

- hypotheticals stored as facts
- stale facts stored as current
- contradictory facts with no review path
- low-quality entity merges

The right design is a **proposal pipeline**:

```text
raw drawer text
  -> segment selection
  -> entity normalization
  -> closed-predicate extraction
  -> temporal / negation / modality checks
  -> candidate triple proposal
  -> review / acceptance
  -> accepted triple written to KG
```

The KG should remain a **trusted store of accepted facts**, not a dumping ground for extraction guesses.

---

## Steelmanned goal

The goal is to connect SwampCastle's strong verbatim memory layer with its weakly-used structured KG layer.
Today:

- verbatim drawer retrieval works
- the KG exists
- but KG population is manual
- so the two systems barely connect

A useful auto-extraction feature should make the KG easier to populate **without destroying trust in it**.

---

## Core recommendation

Build a **candidate-triple proposal system**, not direct KG writes.

### Why proposals first

False negatives are survivable.
False positives in the canonical KG are toxic.

If we write extracted facts directly into the KG too early, the likely long-term outcome is:

- the graph becomes noisy
- contradictions accumulate
- users stop trusting KG queries
- the feature becomes effectively dead

So the pipeline must optimize for:

1. **precision over recall**
2. **provenance over cleverness**
3. **reviewability over automation**

---

## Proposed architecture

## 1. Candidate triple model

Add a proposal model separate from accepted KG facts.

Example shape:

```python
class CandidateTriple(BaseModel):
    candidate_id: str
    subject_text: str
    predicate: str
    object_text: str
    confidence: float
    modality: Literal["asserted", "planned", "hypothetical", "question"]
    polarity: Literal["positive", "negative"]
    valid_from: str | None
    valid_to: str | None
    evidence_drawer_id: str
    evidence_text: str
    source_file: str | None
    status: Literal["proposed", "accepted", "rejected"]
    extractor_version: str
```

### Why this is necessary

The current KG triple model is too thin for extraction output. We need proposal metadata such as:

- confidence
- modality
- polarity
- provenance
- evidence span
- review status
- extractor version

Without that, extracted facts cannot be reviewed or trusted.

---

## 2. Proposal store

Do **not** mix proposed facts into the main `triples` table.

Add separate SQLite tables, for example:

- `candidate_triples`
- optionally `candidate_reviews`

Suggested fields:

```sql
candidate_triples(
  id TEXT PRIMARY KEY,
  subject_text TEXT NOT NULL,
  predicate TEXT NOT NULL,
  object_text TEXT NOT NULL,
  confidence REAL NOT NULL,
  modality TEXT NOT NULL,
  polarity TEXT NOT NULL,
  valid_from TEXT,
  valid_to TEXT,
  evidence_drawer_id TEXT NOT NULL,
  evidence_text TEXT NOT NULL,
  source_file TEXT,
  status TEXT NOT NULL DEFAULT 'proposed',
  extractor_version TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  reviewed_at TEXT
)
```

### Rule

**Proposed facts are not facts.**
They should not appear in normal KG query results until accepted.

---

## 3. Closed predicate vocabulary

Do not let the extractor invent arbitrary predicates.
That leads to ontology sprawl and an unusable graph.

Start with a small, explicit predicate set.

### Technical / project predicates

- `uses`
- `depends_on`
- `migrated_from`
- `migrated_to`
- `deployed_to`
- `blocked_by`
- `fixed_by`
- `owned_by`

### Human / organization predicates

- `works_on`
- `maintains`
- `prefers`
- `decided`
- `reported`
- `requested`

### Lifecycle predicates

- `replaced_by`
- `superseded_by`

### Why closed vocabulary matters

Without this, the extractor will produce variations like:

- `uses`
- `used`
- `used_for`
- `uses_for_auth`
- `migrated_auth_to`

That kills graph queryability.

---

## 4. Segment selection before extraction

Do not run relation extraction uniformly over every raw drawer.
Use existing heuristic extraction to select likely fact-bearing segments first.

SwampCastle already has useful raw material:

- `swampcastle/general_extractor.py`
- `swampcastle/entity_detector.py`

Start by extracting proposals from segments likely to contain:

- decisions
- preferences
- problems
- milestones

### Example

From:

> We switched from Auth0 to Clerk because local testing got simpler.

reasonable proposals are:

- `(project, migrated_from, Auth0)`
- `(project, migrated_to, Clerk)`

From:

> Maybe we should try Clerk someday.

reasonable output is either:

- no accepted fact
- or a low-confidence proposal with `modality="planned"` or `"hypothetical"`

---

## 5. Entity normalization

This is one of the highest-risk parts of the design.

The extractor must map mention text onto canonical entities conservatively.

### Inputs

- existing KG entities
- known project names
- known people names
- explicit aliases

### Strategy

1. exact match first
2. alias match second
3. conservative auto-create only for strong names
4. no fuzzy merge by default

### Example failure mode

If naive normalization merges:

- `Clerk`
- `clerk`
- `the clerk`
- `billing clerk`

into one node, the KG becomes nonsense.

### Design rule

Prefer **no mapping** over a wrong mapping.

---

## 6. Negation, modality, and time

This is non-negotiable.

The extractor must recognize at least:

### Negation

- `we do not use X`
- `X was not the cause`

### Modality

- asserted fact
- planned statement
- hypothetical statement
- question

### Temporal change

- `used to`
- `switched from X to Y`
- `replaced X with Y`
- `until March`
- `since 2025`

### Acceptance rule

Only **asserted**, non-negated candidates should be eligible for default acceptance.
Everything else should remain in the proposal queue unless explicitly reviewed.

---

## 7. Contradiction handling

This must exist from the start.

If the extractor sees:

- `(auth_system, uses, Auth0)` in older evidence
- later `(auth_system, uses, Clerk)`

it must not just append both as current facts indefinitely.

### Minimum strategy

For predicates that look exclusive, such as:

- `uses`
- `migrated_to`
- `deployed_to`

mark conflicts and require review.

Review actions should include:

- accept new fact
- reject proposal
- accept new fact and invalidate prior fact
- edit proposal before acceptance

---

## Workflow recommendation

## Phase 1 — separate CLI, not ingest integration

Start with a separate workflow:

```bash
swampcastle kg extract --dry-run
swampcastle kg extract --wing myapp
swampcastle kg review
swampcastle kg accept <candidate-id>
swampcastle kg reject <candidate-id>
```

### Why not integrate into `gather` immediately

Because extraction quality will be poor at first.
Silent mutation during ingest is the wrong default.

Only after precision is proven should we consider something like:

```bash
swampcastle gather --extract-kg-proposals
```

Even then, proposals only — not direct fact writes.

---

## Review path

The review command should support at least:

- accept
- reject
- accept + invalidate conflicting fact
- edit subject / predicate / object and accept

This gives a human-in-the-loop system first.
Later, an agent can review proposals too.

---

## Scope of the first extractor

Keep the first version deliberately narrow.

## Supported patterns for v1

### Migration

- `switched from X to Y`
- `migrated from X to Y`
- `replaced X with Y`

### Dependency / usage

- `uses X`
- `depends on X`
- `built with X`
- `deployed to X`

### Decision / preference

- `prefer X`
- `decided on X`
- `went with X because Y`

### Ownership / participation

- `Alice works on X`
- `Bob maintains X`

### Defer for later

- open relation extraction
- broad coreference resolution
- LLM-generated predicate invention
- automatic acceptance at scale

---

## Precision strategy

Optimize for **precision**, not recall.

### Initial thresholds

- proposal threshold: about `0.55`
- auto-accept threshold: **disabled initially**

Later, very rigid patterns may be eligible for auto-accept, but only when all of these hold:

- recognized entities
- closed predicate
- no negation
- no hypothetical markers
- no contradiction with accepted facts

---

## Testing strategy

Do not pretend unit tests alone are enough.

## Required labeled corpus

Create a small labeled dataset of evidence passages, for example 100–200 short passages, covering:

- technical migrations
- preferences
- ownership
- bug / fix statements
- plans that should **not** become facts
- contradictory updates over time

Each example should label:

- expected triples
- false triples that must not be accepted
- modality
- polarity
- temporal qualifiers if present

## Metrics

Track at least:

- precision
- recall
- false-positive rate
- contradiction rate
- review acceptance rate

### Decision rule

If precision is low, the feature is not ready.

---

## Pre-mortem

## Failure 1 — garbage graph

**Likelihood:** high  
**Impact:** high

The extractor writes low-confidence triples directly into the KG.
After a few weeks the graph contains:

- plans as facts
- stale facts as current
- duplicate aliases
- contradictory relations

Result: nobody trusts KG queries.

**Mitigation:** proposals only, no blind writes.

---

## Failure 2 — ontology explosion

**Likelihood:** high  
**Impact:** medium-high

Extractor invents many near-duplicate predicates.

Result: graph becomes impossible to query coherently.

**Mitigation:** closed predicate vocabulary from day one.

---

## Failure 3 — entity merge disaster

**Likelihood:** high  
**Impact:** high

Naive normalization merges unrelated entities into one node.

**Mitigation:** conservative normalization and alias-only linking at first.

---

## Failure 4 — ingest slowdown and unpredictability

**Likelihood:** medium  
**Impact:** medium

Extraction is wired into `gather` too early and makes ingest slow, opaque, and hard to debug.

**Mitigation:** separate `kg extract` workflow first.

---

## Recommended implementation order

## Step 1
Add proposal models and proposal tables.

## Step 2
Build a rule-based extractor for a narrow predicate set:

- migrations
- preferences
- decisions
- ownership

## Step 3
Add CLI:

- `kg extract --dry-run`
- `kg review`

## Step 4
Add entity normalization and contradiction checks.

## Step 5
Add acceptance path from proposal store to KG.

## Step 6
Only then consider optional LLM assistance for low-confidence proposals.

---

## Highest-risk issue

The highest-risk issue is **false certainty**.

Not missing facts.
Not low recall.

The real danger is writing false facts into the canonical KG and teaching users that the graph is not trustworthy.

That is the failure mode the design must prevent.

---

## Recommendation

Build:

1. proposal tables
2. closed-predicate extractor
3. entity normalization
4. review workflow
5. accepted-fact write path
6. only later, optional LLM assistance

Anything more ambitious than that for v1 is overreach.
