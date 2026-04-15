# KG Auto-Extraction Pipeline — Concrete Implementation Plan

Date: 2026-04-14
Status: implementation plan
Related design note: `docs/reviews/kg_auto_extraction_pipeline.md`

## Goal

Build a **proposal-first KG auto-extraction pipeline** that connects raw drawers to the knowledge graph **without polluting the canonical KG**.

The pipeline must:

- extract **candidate facts** from drawers
- preserve **evidence and provenance**
- avoid writing directly to the accepted KG by default
- support **review / accept / reject**
- remain **precision-first**

This is not a "ship a magic extractor" plan. It is a plan to build a safe, reviewable fact proposal system.

---

## Non-goals for v1

These are explicitly out of scope for the first implementation wave:

- direct auto-write into accepted KG during `gather`
- arbitrary open relation extraction
- fuzzy entity merge logic
- full LLM dependency for extraction
- global auto-accept of extracted facts
- perfect coreference resolution
- production-grade sparse/semantic contradiction solver

If any of these creep into v1, the scope is wrong.

---

## Design decisions

## 1. Proposals are stored separately from accepted facts

Accepted KG facts and extracted candidate facts are different objects.

### Accepted facts
- authoritative
- returned by normal KG queries
- written only by explicit acceptance or manual add

### Candidate facts
- reviewable
- confidence-scored
- provenance-rich
- not returned by normal KG queries

---

## 2. Closed predicate vocabulary

V1 extractor uses a small predicate set. No arbitrary relation names.

Initial predicate set:

### Technical / project
- `uses`
- `depends_on`
- `migrated_from`
- `migrated_to`
- `deployed_to`
- `blocked_by`
- `fixed_by`
- `owned_by`

### Human / org
- `works_on`
- `maintains`
- `prefers`
- `decided`
- `reported`
- `requested`

### Lifecycle
- `replaced_by`
- `superseded_by`

Anything outside this set is rejected in v1.

---

## 3. Proposal-first workflow, not ingest mutation

V1 workflow:

```bash
swampcastle kg extract --dry-run
swampcastle kg extract --apply-proposals
swampcastle kg review
swampcastle kg accept <candidate-id>
swampcastle kg reject <candidate-id>
```

`gather` does **not** write extracted facts into the KG in v1.

If we later allow gather integration, it should be:
- proposal-only
- opt-in
- never default

---

## 4. Precision over recall

Policy:
- proposal threshold: modest
- auto-accept threshold: disabled in v1
- anything ambiguous remains a proposal

This is the only sane tradeoff.

---

## Proposed implementation architecture

## A. Data model layer

### New file
- `swampcastle/models/kg_candidates.py`

### New models

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
    created_at: str | None = None
    reviewed_at: str | None = None

class CandidateTripleFilter(BaseModel):
    status: Literal["proposed", "accepted", "rejected"] | None = None
    predicate: str | None = None
    min_confidence: float | None = None
    wing: str | None = None
    room: str | None = None
    limit: int = 50
    offset: int = 0

class CandidateReviewCommand(BaseModel):
    candidate_id: str
    action: Literal["accept", "reject", "accept_and_invalidate_conflict"]
    subject_text: str | None = None
    predicate: str | None = None
    object_text: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
```

### Also update
- `swampcastle/models/__init__.py`

---

## B. Storage layer

## Decision

For MVP, extend the existing graph-storage path rather than inventing a parallel subsystem.

### Option chosen
Add candidate-triple methods to the graph storage contract.

### Files
- `swampcastle/storage/base.py`
- `swampcastle/storage/sqlite_graph.py`
- `swampcastle/storage/memory.py`
- `swampcastle/storage/postgres.py`

### Why this choice
It keeps proposal data physically adjacent to the KG and avoids a second unrelated storage abstraction.

### Contract additions to `GraphStore`
Add methods such as:

```python
propose_triple(...)
list_candidate_triples(...)
get_candidate_triple(...)
set_candidate_status(...)
delete_candidate_triple(...)
```

### Important note about Postgres
There are two valid ways to handle Postgres in v1:

#### Conservative option
Implement proposal methods in:
- SQLite
- InMemory

And raise `NotImplementedError` in Postgres until the local MVP is proven.

#### Full-parity option
Implement the same candidate tables in Postgres in the first pass.

### Recommendation
Use the **conservative option** unless there is an immediate user need for proposal extraction on Postgres.
The local backend is the right place to prove the workflow first.

---

## C. SQLite schema additions

### File
- `swampcastle/storage/sqlite_graph.py`

### New tables

```sql
CREATE TABLE IF NOT EXISTS candidate_triples (
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
    wing TEXT,
    room TEXT,
    status TEXT NOT NULL DEFAULT 'proposed',
    extractor_version TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_candidate_status ON candidate_triples(status);
CREATE INDEX IF NOT EXISTS idx_candidate_predicate ON candidate_triples(predicate);
CREATE INDEX IF NOT EXISTS idx_candidate_confidence ON candidate_triples(confidence);
CREATE INDEX IF NOT EXISTS idx_candidate_location ON candidate_triples(wing, room);
```

### Why include wing/room here
Because review workflows and extraction passes will often be scoped by wing/room. That filter should be cheap.

---

## D. Extraction layer

### New file
- `swampcastle/mining/extractors.py`

### Responsibilities
1. pick candidate-bearing segments
2. detect entities
3. normalize entities
4. map phrase patterns to closed predicates
5. score confidence
6. attach evidence and modality

### Suggested functions

```python
def extract_candidate_triples_from_drawer(drawer: dict, *, extractor_version: str) -> list[CandidateTriple]

def extract_candidate_triples_from_text(text: str, *, source_meta: dict, extractor_version: str) -> list[CandidateTriple]

def normalize_entity(text: str, known_entities: dict) -> str | None

def detect_modality(text: str) -> str

def detect_polarity(text: str) -> str

def detect_time_bounds(text: str) -> tuple[str | None, str | None]
```

### V1 extraction strategy
Use rules, not LLMs.

#### Segment selection inputs
Reuse:
- `general_extractor.py`
- maybe selected heuristics from `entity_detector.py`

#### Supported sentence families for v1
- `switched from X to Y`
- `migrated from X to Y`
- `replaced X with Y`
- `uses X`
- `depends on X`
- `built with X`
- `deployed to X`
- `Alice works on X`
- `Bob maintains X`
- `we decided on X`
- `I prefer X`

#### Things to reject or downgrade
- questions
- hypotheticals
- future plans
- highly ambiguous subject/object pairs

---

## E. Service layer

### New file
- `swampcastle/services/kg_proposals.py`

### New service
`KGProposalService`

### Responsibilities
- run extraction over drawers
- store proposals
- list proposals
- accept/reject proposals
- on accept, call existing graph write path
- optionally invalidate conflicting facts

### Suggested API

```python
class KGProposalService:
    def extract_from_drawers(...)
    def list_proposals(...)
    def accept(...)
    def reject(...)
```

### Why a separate service
Do not cram this into `GraphService` immediately.
`GraphService` handles accepted facts and graph queries.
Proposal extraction and review is a separate concern.

---

## F. Castle wiring

### File
- `swampcastle/castle.py`

### Add
```python
self.kg_proposals = KGProposalService(...)
```

The service should receive:
- graph store
- collection store
- wal writer

---

## G. CLI surface

### Files
- `swampcastle/cli/main.py`
- `swampcastle/cli/commands.py`

### New commands

```bash
swampcastle kg extract [--wing NAME] [--room NAME] [--dry-run] [--limit N]
swampcastle kg review [--status proposed] [--predicate uses] [--limit N]
swampcastle kg accept <candidate-id>
swampcastle kg reject <candidate-id>
```

### Optional later command
```bash
swampcastle kg accept-conflict <candidate-id>
```
or fold into:
```bash
swampcastle kg accept <candidate-id> --invalidate-conflicts
```

### CLI philosophy for v1
- no interactive TUI needed yet
- plain text list/review output is fine
- optimize for correctness, not polish

---

## H. MCP surface (later in same wave or next)

### File
- `swampcastle/mcp/tools.py`

Potential tools:
- `swampcastle_kg_extract`
- `swampcastle_kg_list_candidates`
- `swampcastle_kg_accept_candidate`
- `swampcastle_kg_reject_candidate`

### Recommendation
Do not add MCP tools until CLI flow and storage model are proven.
Otherwise you expose an unstable workflow to agents too early.

---

## Milestone plan

## PR 1 — Proposal storage and review skeleton

### Scope
- add candidate models
- add storage methods
- add SQLite schema
- add InMemory implementation
- add service skeleton
- add CLI skeleton (`kg review`, `accept`, `reject`)

### Files
- `swampcastle/models/kg_candidates.py`
- `swampcastle/models/__init__.py`
- `swampcastle/storage/base.py`
- `swampcastle/storage/sqlite_graph.py`
- `swampcastle/storage/memory.py`
- `swampcastle/services/kg_proposals.py`
- `swampcastle/castle.py`
- `swampcastle/cli/main.py`
- `swampcastle/cli/commands.py`

### Tests
- `tests/test_kg_candidate_models.py`
- `tests/test_storage_sqlite_graph_candidates.py`
- `tests/test_storage_memory_candidates.py`
- `tests/test_kg_proposal_service.py`
- `tests/test_cli_kg_review.py`

### Acceptance criteria
- proposals can be created/listed/accepted/rejected
- accepted proposals write real KG triples
- rejected proposals remain out of KG queries

---

## PR 2 — Rule-based extractor v1

### Scope
- implement extractor rules for narrow predicate set
- extract proposals from existing drawers
- support dry-run extraction

### Files
- `swampcastle/mining/extractors.py`
- `swampcastle/services/kg_proposals.py`
- `swampcastle/cli/commands.py`
- `swampcastle/cli/main.py`

### Tests
- `tests/test_kg_extractor_rules.py`
- `tests/test_kg_extract_cli.py`
- `tests/test_kg_extraction_flow.py`

### Example test cases
- migration sentence produces two proposals
- hypothetical sentence produces proposal with `modality != asserted`
- question produces no accepted proposal candidate
- negated sentence does not become positive fact

### Acceptance criteria
- dry-run extraction lists useful candidate triples
- proposal status remains `proposed`
- no direct KG mutation during extraction

---

## PR 3 — Review workflow + contradiction handling

### Scope
- accept/reject CLI
- conflict detection for exclusive predicates
- optional accept-and-invalidate flow

### Files
- `swampcastle/services/kg_proposals.py`
- `swampcastle/storage/sqlite_graph.py`
- `swampcastle/cli/commands.py`
- optionally `swampcastle/services/graph.py`

### Tests
- `tests/test_kg_review_flow.py`
- `tests/test_kg_conflict_detection.py`

### Acceptance criteria
- conflicting proposal can be reviewed explicitly
- accept-and-invalidate path updates KG correctly
- accepted facts appear in normal KG query results
- rejected facts do not

---

## PR 4 — Optional gather integration (only after precision is proven)

### Scope
- optional `--extract-kg-proposals` flag in gather
- proposal-only extraction during ingest

### Files
- `swampcastle/mining/miner.py`
- `swampcastle/cli/main.py`
- `swampcastle/cli/commands.py`

### Acceptance criteria
- gather remains default-safe
- extraction is explicit and proposal-only
- no silent KG mutation

---

## Test strategy

## Unit tests

### Models
- proposal validation
- review command validation
- confidence bounds

### Extractor
- migration pattern extraction
- usage pattern extraction
- ownership pattern extraction
- negation detection
- modality detection
- time-bound detection

### Storage
- proposal insert/list/update/reject/accept
- persistence in SQLite
- in-memory parity

---

## Integration tests

### End-to-end flow
1. add drawers
2. run proposal extraction
3. list proposals
4. accept one proposal
5. verify KG query sees accepted fact
6. reject another proposal
7. verify KG query ignores it

### Contradiction flow
1. existing accepted fact
2. extracted conflicting proposal
3. accept with invalidate
4. verify old fact expired / new fact current

---

## Labeled corpus work

This should start in parallel with PR 2, even if small.

### New test asset directory
- `tests/fixtures/kg_extraction/`

### Format
A set of JSON or YAML fixtures with:
- input evidence text
- expected proposals
- forbidden proposals
- modality/polarity expectations

### Goal
Measure precision explicitly. Do not rely on anecdotal extractor success.

---

## Open technical questions

## 1. Extend `GraphStore` or create a separate proposal-store ABC?

### Recommendation
Extend `GraphStore` for now.

### Why
- simpler MVP
- proposal data lives alongside KG data
- less wiring complexity

### Cost
- need to update SQLite + InMemory
- Postgres either must implement or explicitly raise `NotImplementedError`

---

## 2. Should accepted proposals remain stored in proposal tables?

### Recommendation
Yes.

### Why
You want a permanent audit trail linking:
- evidence
- proposal
- review decision
- accepted fact

Do not throw this away.

---

## 3. Should acceptance write exact text entities or normalized entities only?

### Recommendation
Store:
- normalized entity names in KG
- original `subject_text` / `object_text` in proposal record

That preserves both reviewability and KG cleanliness.

---

## 4. Should v1 support Postgres?

### Recommendation
Only if there is immediate demand.
Otherwise:
- implement SQLite + InMemory first
- raise a clear `NotImplementedError` in Postgres proposal methods
- add Postgres parity later

That keeps the MVP small and honest.

---

## Risks and mitigations

## Risk 1 — predicate sprawl
Mitigation: hardcoded predicate set in extractor.

## Risk 2 — alias merge mistakes
Mitigation: exact/alias-only normalization in v1.

## Risk 3 — proposal flood
Mitigation:
- confidence threshold
- wing/room filters
- extractor limited to fact-bearing segments first

## Risk 4 — users assume extraction means truth
Mitigation:
- separate proposal store
- review-first CLI
- docs that repeatedly say proposals are not facts

---

## Minimal first release definition

V1 is successful if all of these are true:

- candidate triples can be extracted from drawers
- proposals are stored separately from the KG
- proposals can be listed/reviewed
- accepted proposals become normal KG facts
- rejected proposals do not
- migration / usage / ownership patterns work with decent precision
- no automatic blind writes happen during ingest

If we achieve that, the feature is real.
If we skip any of that, we are faking it.

---

## Recommended next action

Start with **PR 1 only**:
- proposal model
- proposal storage
- review skeleton
- accept/reject flow

Do **not** start with extractor logic first.
Without the proposal storage and review workflow, the extractor has nowhere safe to put its output.
