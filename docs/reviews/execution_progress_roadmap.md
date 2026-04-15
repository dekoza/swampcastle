# Execution Progress Roadmap

Date: 2026-04-14
Source plan: `/home/minder/.pi/agent/sessions/--home-minder-projekty-AI-swampcastle--/2026-04-14T17-27-09-713Z_4b613336-753a-4cfb-9310-bbde768a4046.plan.md`
Status scope: code and tests in this repository after the latest completed wave

---

## Purpose

This document gives a top-down view of:

- what was planned
- what has already been delivered
- what should happen next
- what can wait

It is intentionally execution-focused, not marketing-focused.

---

## Current snapshot

Latest verified non-integration test run:

- **922 passed**
- **2 skipped**
- **5 deselected**

Command:

```bash
uv run pytest tests/ --ignore=tests/integration --ignore=tests/benchmarks -q --tb=short
```

---

## Summary status by plan area

| Area | Status | Notes |
|---|---:|---|
| Priority A — correctness / security | **Complete** | Drawer IDs, sync auth, embedder cache safety, SQLite KG concurrency fixed |
| Priority B — scalability / robustness | **Mostly complete** | Graph caching, diary read fix, status() scaling fixed |
| Priority C — retrieval quality | **Partially complete** | Chunking improved; lexical rerank + hybrid candidate generation added; still not a full sparse/reranker stack |
| Priority D — long-term features | **Started** | KG proposal extraction pipeline is now real; retention and internal reranker still untouched |

---

## DONE

## 1. Correctness and safety foundation

### Drawer ID correctness
Delivered:
- full-content hashing instead of first-100-char hashing
- field-separator fix to avoid hash ambiguity across `wing` / `room` boundaries
- migration guidance corrected

Impact:
- distinct drawers are no longer silently dropped due to ID collisions

Related commits:
- `ce0d751`
- `931694c`

### Sync server authentication
Delivered:
- optional Bearer-token auth on sync server
- auth-aware sync client
- docs aligned with actual behavior

Impact:
- sync is no longer implicitly unauthenticated when auth is enabled

Related commits:
- `27d7e98`
- `f3e3c43`
- `791e143`

### Embedder cache thread-safety
Delivered:
- lock-protected cache creation
- deterministic concurrency tests
- fixture isolation improved

Impact:
- concurrent cache misses no longer instantiate multiple embedders for the same key

Related commits:
- `d508f9e`
- `6a7a234`

### SQLite KG concurrency safety
Delivered:
- one SQLite connection per thread
- serialized writes
- WAL + busy_timeout per connection

Impact:
- removed real thread-contention failures (`InterfaceError`, `DatabaseError`, sqlite `SystemError`)

Related commit:
- `80ce532`

---

## 2. Robustness and scaling fixes

### Graph summary caching
Delivered:
- cached room-summary graph in `GraphService`
- cache invalidation on drawer writes/deletes/diary writes
- Castle wiring for invalidation

Impact:
- `traverse()`, `find_tunnels()`, and `graph_stats()` no longer rescan the collection on every read-only call

Related commit:
- `8732bc8`

### Diary read fix
Delivered:
- removed quadratic offset-pagination path
- single capped fetch + heap selection
- honest docstring about tradeoffs

Impact:
- avoids the worst storage-scan behavior while still returning the most recent entries

Related commit:
- `f639dd9`

### `miner.status()` fix
Delivered:
- real total count via `count()`
- paginated metadata scan
- no silent truncation above 10k drawers

Impact:
- status output is no longer lying about large castles

Related commit:
- `b2e3c08`

---

## 3. Retrieval improvements

### Chunking improvements (first pass)
Delivered:
- paragraph -> line -> sentence -> word boundary preference
- overlap start realigned to word boundary

Impact:
- fewer mid-sentence and mid-word splits
- better chunk quality for prose retrieval

Related commit:
- `b7f1989`

### Lexical rerank and hybrid retrieval
Delivered:
- optional `lexical_rerank`
- optional `hybrid`
- lexical candidate generation via collection scan
- merged dense + sparse candidate reranking
- `context` used only in reranking, never embedded

Impact:
- dense retrieval can now recover exact lexical matches it previously missed

Related commits:
- `abc3039`
- `7e07034`

### Query sanitizer hardening
Delivered:
- labeled-tail extraction step before generic heuristics
- support for:
  - `Query:`
  - `Search query:`
  - `User query:`
  - `Actual query:`
  - `Question:`
  - `Task:`
  - `<user_query>...</user_query>`
  - `<query>...</query>`

Impact:
- contaminated single-line prompts are much less likely to turn into tail-junk queries

Related commit:
- `a69213f`

---

## 4. AAAK policy hardening

Delivered:
- CLI defaults to preview mode
- `--apply` required to persist AAAK metadata
- docs updated to reflect preview-first policy

Impact:
- lossy summarization is no longer the accidental default path

Related commit:
- `48f2f0e`

---

## 5. KG proposal extraction pipeline (MVP)

### Proposal infrastructure
Delivered:
- candidate-triple models
- proposal storage in SQLite + in-memory backends
- proposal service skeleton
- review / accept / reject CLI

Related commit:
- `e1ea49a`

### Rule-based extraction
Delivered:
- narrow, precision-first extractor
- `kg extract`
- dry-run and apply modes
- idempotent proposal persistence

Related commit:
- `ac8e603`

### Conflict handling
Delivered:
- conflict markers for exclusive predicates
- accept-with-invalidation workflow
- CLI support for `--invalidate-conflicts`

Related commit:
- `e234b2e`

### Gather integration
Delivered:
- optional `--extract-kg-proposals` on gather
- works for project mining and conversation mining
- remains proposal-only and opt-in

Related commit:
- `c28cc34`

---

## 6. Benchmark honesty

Delivered:
- threats-to-validity sections added to benchmark docs

Impact:
- docs now distinguish retrieval quality from end-to-end agent quality
- no-LLM path vs reranked path are described more honestly

Related commit:
- `90ab9fe`

---

## NEXT

These are the highest-value next steps.

## 1. Extraction quality and evaluation discipline

Why this is next:
- the proposal pipeline now exists
- the main bottleneck is no longer storage/plumbing
- the real risk is low extraction precision

Recommended work:
- add labeled extraction fixtures under `tests/fixtures/kg_extraction/`
- measure:
  - precision
  - recall
  - false-positive rate
  - contradiction rate
  - acceptance rate during review
- expand extractor rules only after measurement

Concrete first tasks:
- create 50–100 labeled passages
- add `tests/test_kg_extraction_fixture_corpus.py`
- fail builds when precision drops below an agreed threshold

---

## 2. Review workflow ergonomics

Why this matters:
- the proposal system exists, but review UX is still minimal
- acceptance is possible, but editing and triaging are still clumsy

Recommended work:
- add edit-before-accept support
- add better `kg review` filtering and formatting
- optionally add conflict-only review mode

Concrete first tasks:
- support subject/predicate/object edits in CLI output path more explicitly
- add `kg review --conflicts-only`
- add paginated review output for large proposal sets

---

## 3. Entity normalization

Why this matters:
- rule-based extraction is useful now, but entity quality is still fragile
- wrong merges will poison the KG faster than missing merges

Recommended work:
- exact/alias-only normalization first
- no fuzzy matching in the first pass
- reuse project-specific known entities where possible

Concrete first tasks:
- add alias map support
- normalize extracted entities before proposal persistence
- track original text separately from normalized text

---

## 4. Retrieval validation

Why this matters:
- retrieval changed materially
- chunking changed materially
- hybrid search changed materially
- we still have not closed the benchmark validation loop promised in the plan

Recommended work:
- run quick benchmark baselines again
- compare dense-only vs lexical rerank vs hybrid
- validate no unacceptable regressions in latency / recall

Concrete first tasks:
- save benchmark snapshots under `benchmarks/`
- document results in a short update note

---

## LATER

These should happen, but not before the “NEXT” items above.

## 1. Real sparse index / stronger hybrid retrieval

Current hybrid mode uses collection scans for lexical candidates.
That is good enough for a first real hybrid implementation, but it is not the final architecture.

Later work:
- proper sparse index
- better candidate merging
- possibly BM25 or equivalent scoring backend

---

## 2. Internal reranker service

Potential later addition:
- local reranker model
- optional remote reranker integration
- stronger ranking than lexical coverage alone

This should only happen after benchmark discipline exists.

---

## 3. Postgres parity for candidate proposals

Current status:
- SQLite + in-memory proposal storage implemented
- Postgres proposal storage intentionally deferred

This is fine for MVP.
Only do this when there is an actual deployment need.

---

## 4. Retention / merging policies

Still not started.
This remains important for any serious long-term memory story.

Later work:
- repeated-fact merging
- stale-proposal cleanup
- retention policies for old drawers / proposals
- proposal aging / review SLA tracking

---

## Risks going forward

## Risk 1 — extractor precision drifts downward
As rule coverage expands, false positives can explode quietly.

Mitigation:
- fixture corpus
- precision threshold
- review acceptance metrics

## Risk 2 — review workflow stays too weak
If reviewing proposals is annoying, users won’t do it, and the proposal system will stagnate.

Mitigation:
- better CLI review ergonomics before expanding extraction scope too much

## Risk 3 — retrieval improvements outpace validation
We already changed chunking and search ranking behavior. Without validation, we can drift into unverified improvements.

Mitigation:
- benchmark reruns before larger retrieval changes

## Risk 4 — KG scope expands faster than ontology discipline
The more predicates and patterns we add, the more likely the graph becomes inconsistent.

Mitigation:
- keep predicate set closed unless there is strong evidence for expansion

---

## Decision gates

Use these gates before moving into later phases.

## Gate A — before expanding extractor rules
Required:
- fixture corpus exists
- current precision measured
- review CLI is usable

## Gate B — before adding LLM-assisted extraction
Required:
- rule-based pipeline already useful
- precision baseline exists
- review flow stable

## Gate C — before gather-time extraction becomes a common recommendation
Required:
- proposal generation proven low-noise on real projects
- repeated runs proven idempotent
- conflict markers proven useful in review

---

## Bottom line

The project is no longer missing the foundation.
The foundation is there.

What is done:
- correctness and safety foundation
- scaling fixes
- first retrieval improvements
- benchmark honesty improvements
- full proposal-first KG extraction MVP

What should happen next:
- **measure extraction quality**
- **improve review UX**
- **add conservative entity normalization**
- **validate retrieval changes with benchmarks**

Do not jump straight to bigger extraction ambition until those are in place.
