Architecture & Claims Critical Review — SwampCastle
===================================================

Date: 2026-04-14
Author: Automated review (assistant)

Purpose
-------
Persist a concise, actionable record of the architectural review and the concrete shortcomings found while auditing the codebase. This file is intended to be the authoritative starting point for planning and implementing fixes.

TL;DR
-----
SwampCastle is a robust, pragmatic system for storing verbatim text and performing semantic search over that text. The core retrieval pipeline and local storage (LanceDB + SQLite) are well-engineered and benchmarked. However, the project's marketing and many docs claim a much broader "long-term memory" role than the code supports. The main gaps are:

- The knowledge graph is manual and not automatically populated from verbatim text.
- AAAK (lossy summarization) reduces retrieval quality versus raw text.
- Sync, concurrency, and scale behaviors have multiple fragile or unsafe points.
- Chunking, dedup, and sanitizer heuristics are brittle and can harm correctness.

If the aim is to evolve SwampCastle from "fast verbatim memory store" to a full long-term memory system for agents, the codebase needs prioritized architectural work, new tests, and careful incremental improvements.

High-level findings (short)
--------------------------
1. Benchmarks are real but narrowly scoped: LongMemEval measures retrieval of verbatim passages and therefore favors raw-storage + semantic search. The 100% figure requires an LLM reranker (contradicts the "no LLM" pitch).
2. The knowledge graph (SQLite) is not auto-populated and is not synchronized with the collection store. Graph-powered features are therefore only as good as manual KG writes.
3. Chunking: fixed 800-char chunks with only 100-char overlap — brittle and likely to split important facts.
4. Default embedder is an older 384d MiniLM model; no hybrid (sparse+dense) retrieval in production, and no deployed cross-encoder reranker.
5. Concurrency & threading: global embedder cache and shared SQLite connection lack safe concurrency controls.
6. Sync is unauthenticated, uses wall-clock last-writer-wins conflict resolution, and syncs only the collection (not KG).
7. AAAK compression is lossy and demonstrably reduces retrieval quality when used as the stored content.
8. Several operations (graph build, diary read, status) scan large portions of data in Python and will not scale.
9. Drawer ID and diary ID generation have collision/correctness risk.
10. Query sanitizer addresses a real problem (system prompt contamination) but uses fragile heuristics.

Detailed findings (with code pointers)
-------------------------------------
1) Benchmark framing and limits
   - Files: benchmarks/ (BENCHMARKS.md, BENCHMARKS_V4.md, results files)
   - Claim: 96.6% R@5 (LongMemEval) — accurate for raw verbatim retrieval but does not prove "superior memory" beyond retrieval recall.
   - 100% requires LLM reranker; LoCoMo perfect scores use top-k > sessions (mathematical consequence), not general improvement.
   - Risk: marketing conflates retrieval benchmarks with the much broader concept of long-term memory.

2) Knowledge graph (KG)
   - Files: swampcastle/storage/sqlite_graph.py, swampcastle/services/graph.py
   - Observation: KG writes occur via explicit API calls (swampcastle_kg_add). There is no automated extractor to populate KG from text.
   - `GraphService._build_graph()` performs metadata scans over the collection and derives structural edges from metadata rather than querying the KG.
   - Sync: sync engine (swampcastle/sync.py) and sync server (swampcastle/sync_server.py) operate on the collection store only — KG is not synced.
   - Risk: users may assume KG is a live, canonical facts store; it is not.

3) Chunking & ingestion
   - Files: swampcastle/mining/miner.py (CHUNK_SIZE=800, CHUNK_OVERLAP=100)
   - Problem: fixed character-length splitting can break sentences/semantic units. Overlap is small; content spanning the boundary may become unrecoverable in retrieval.
   - Skeleton extraction path exists for very large files but is heuristic-driven.

4) Embedding and retrieval
   - Files: swampcastle/embeddings.py, swampcastle/storage/lance.py, swampcastle/services/search.py
   - Default: OnnxEmbedder -> all-MiniLM-L6-v2 (384d). Good for CPU, but not state-of-the-art by 2026.
   - Retrieval: LanceCollection.query() uses the embedder, cosine metric; SearchService uses only dense search with optional metadata filters. No hybrid BM25 or cross-encoder rerank in production path.
   - `SearchQuery.context` exists but is unused.

5) AAAK compression
   - Files: swampcastle/dialect.py, docs/aaak.md
   - Effect: Benchmarks show AAAK mode reduces R@5 from 96.6% → 84.2%. AAAK is lossy by design and should be treated as an optional, application-specific summarization — not a general recommended storage format.

6) Sync & security
   - Files: swampcastle/sync.py, swampcastle/sync_server.py
   - Sync server has no authentication. Version vector (JSON) and last-writer-wins on `updated_at` timestamps are brittle (clock skew risk). The sync engine only applies to the collection store; KG isn't replicated.

7) Concurrency and thread-safety
   - Files: swampcastle/embeddings.py (_embedder_cache global), swampcastle/storage/sqlite_graph.py (sqlite connection with check_same_thread=False), swampcastle/castle.py (AsyncCastle uses anyio to thread off to sync Castle).
   - Problem: shared objects used across threads without explicit locks. Race conditions possible during embedder init and DB access under concurrent requests.

8) Scan-heavy operations
   - Files: swampcastle/services/graph.py (`_build_graph()`), swampcastle/services/vault.py (diary_read loads up to 10,000), swampcastle/mining/miner.py (status shows top 10k)
   - Problem: these operations pull large amounts of data into memory for processing. They must be redesigned (paging, precomputed stats, indices).

9) ID generation collisions
   - Drawer ID: models/drawer.py AddDrawerCommand.drawer_id() uses first 100 chars to hash. Two different contents with identical prefixes collide.
   - Diary ID: VaultService.diary_write uses timestamp + sha256 of first 50 chars — collision risk on high-frequency writes.

10) Dedup heuristics and cost
    - Files: swampcastle/dedup.py
    - Dedup algorithm queries for each candidate document against 'kept' set — worst-case O(N^2) query pattern. Threshold defaults and batching are coarse.

11) Query sanitizer
    - Files: swampcastle/query_sanitizer.py
    - Good to have, but relies on question mark detection and tail extraction heuristics. Edge cases exist (imperative queries, multi-sentence prompts, LLMs placing the question early).

12) Postgres backend maturity
    - Files: swampcastle/storage/postgres.py
    - Postgres backend exists but has long codepaths and optional imports. Integration is tested but may be less exercised in CI than Lance/SQLite.

Concrete risks and failure modes
-------------------------------
- Silent data loss: drawer_id collisions cause `add_drawer` to return `already_exists` without storing a distinct second record.
- Privacy/security: unauthenticated sync server exposes all drawers to anyone who can reach the host.
- Data divergence: KG and collection drift because KG is not auto-populated and not replicated.
- Race conditions: concurrent embedder init or concurrent writes to SQLite without adequate locking may lead to crashes or corrupted state.
- Performance cliffs: `_build_graph()` and unbounded `get()` queries will fail or time out on large castles (>100k drawers).
- Wrong troubleshooting assumptions: marketing framing suggests "no LLM required" as a universal advantage; in reality, getting top-tier benchmark results used an LLM reranker.

Prioritized next steps (suggested)
----------------------------------
These are prioritized from high-impact & low-effort to larger structural work.

1) Fix drawer ID collision (high priority)
   - Make drawer_id use a full content hash (or include full content hash instead of first 100 chars) and/or a monotonic seq to avoid collisions. Update AddDrawerCommand.drawer_id().
   - TDD: write unit test verifying two different contents with identical first 100 chars produce different IDs and are both stored.

2) Hardening sync (high priority)
   - Add optional authentication for sync server (API key or token). Document threat model.
   - Change sync conflict resolution doc to call out clock skew and recommend NTP or monotonic counters. Consider server-assigned sequence IDs for authoritative ordering.
   - TDD: integration test for sync push/pull with mock nodes, clock skew scenarios.

3) Make embedder cache thread-safe (medium priority)
   - Add a simple lock around embedder creation (threading.Lock) and ensure embedder constructors are idempotent.
   - TDD: unit test that parallel get_embedder calls don't create multiple instances and don't raise.

4) Protect SQLite access (medium priority)
   - Revisit `check_same_thread=False` usage. Use a connection pool or per-thread connections, or serialize write access using a lock.
   - TDD: stress test/distributed test that simulates concurrent KG writes/reads.

5) Make graph operations incremental or cached (medium-high)
   - Avoid rebuilding the entire graph on each `traverse()` call. Cache node/edge summaries and invalidate incrementally when new drawers are added or metadata changes.
   - TDD: performance integration test for `traverse()` on 100k synthetic drawers verifying latency < X ms.

6) Revisit chunking & overlap (medium)
   - Move to sentence-aware chunking with configurable max tokens and larger overlaps (or content-based split e.g., using newline/paragraphs or tokenizer-based heuristics).
   - TDD: unit tests that ensure multi-sentence facts remain recoverable (search for sentence that previously would have been split and missed).

7) Make AAAK explicit and opt-in (low-medium)
   - Update docs: AAAK should never be the default storage format. Make `distill` explicitly opt-in and warn about retrieval degradation.
   - Add tests demonstrating AAAK vs raw retrieval differences.

8) Add hybrid retrieval & optional reranker (longer-term)
   - Implement hybrid BM25 + dense candidate retrieval and provide a cross-encoder reranker in the benchmark tools (optional use in production).
   - TDD: add benchmark integration tests that reproduce LongMemEval numbers for raw/dense/hybrid+rerank modes.

9) Improve query sanitizer (longer-term)
   - Replace fragile heuristics with small LLM-assisted extraction or a stronger regex+semantic model; document failure modes.
   - TDD: unit tests with diverse contaminated prompts, covering edge cases used in Issue #333.

10) Add retention/forgetting policies (long-term)
    - Provide configurable TTLs, priority aging, or merge policies for repeated/contradictory facts.
    - TDD: tests to simulate growth and validate that retention policies keep relevant recall and control index size.

Testing roadmap (required)
--------------------------
Per AGENTS.md the project must be TDD-first for all changes. Suggested test areas to add immediately:

- Unit tests
  - Drawer ID uniqueness and add_drawer return semantics (models/drawer.py, services/vault.py)
  - get_embedder concurrency and singleton behavior (embeddings.py)
  - query_sanitizer edge cases (query_sanitizer.py) — more fuzzing tests
  - AAAK compression coverage and compression_stats expectations (dialect.py)

- Integration tests
  - Sync push/pull between two temporary castles and version vector correctness, including clock skew test.
  - GraphService traversal and find_tunnels on a synthetic dataset with known structure — measure performance.
  - Miner ingest pipeline with sentence/skeleton split variants and verify chunk integrity.

- Performance tests (benchmarks)
  - Re-run curated LongMemEval, LoCoMo, ConvoMem reproductions after fixes to ensure no regression.
  - Add scale smoke tests: 100k drawers with random metadata to exercise _build_graph, query latency, and sync throughput.

- E2E tests
  - For MCP server: a Playwright-style test isn't necessary (no frontend), but a small integration test that runs the FastAPI sync server and performs push/pull flows would be required.

Documentation & communication
-----------------------------
- Update README/docs to separate "verbatim retrieval store" from a claim of "complete long-term memory system".
- Mark AAAK as experimental and include the measured impact in docs/aaak.md.
- Add a "Limitations" or "Threats to validity" section to BENCHMARKS.md explaining dataset assumptions (verbatim presence of answers, synthetic nature, top-k caveats).

Files to read / touch (quick index)
----------------------------------
- swimmpcastle core
  - swampcastle/castle.py
  - swampcastle/services/search.py
  - swampcastle/embeddings.py
  - swampcastle/storage/lance.py
  - swampcastle/mining/miner.py
  - swampcastle/services/vault.py
  - swampcastle/services/graph.py
  - swampcastle/storage/sqlite_graph.py
  - swampcastle/dialect.py
  - swampcastle/sync.py
  - swampcastle/sync_server.py
  - swampcastle/models/drawer.py
  - swampcastle/query_sanitizer.py
  - swampcastle/dedup.py

Recommended short-term checklist for implementers
-------------------------------------------------
1. Add failing tests that capture each of the behaviors above (ID collision, sync auth missing, embedder race) — one failing test per issue.
2. Fix drawer ID generation; make test pass.
3. Add minimal auth to sync server and tests that assert 401 without token.
4. Make embedder cache creation thread-safe and add concurrency test.
5. Replace heavy scans (graph, diary read) with paged APIs or precomputed indices and add performance assertions.

Ownership & follow-ups
----------------------
- Suggested owners for starting work: whoever maintains `mining/` (ingest, chunking), the storage team (LanceDB & postgres adapters), and the sync team (sync.py / sync_server.py).
- Make incremental PRs: each PR should add tests first (TDD), implement fix, then add a benchmark/integration verification where applicable.

Appendix — Short list of concrete code edits to consider first
-------------------------------------------------------------
1. models/drawer.py AddDrawerCommand.drawer_id() — use full content hash and include a monotonic counter if needed.
2. sync_server.py — add token-based auth (Basic or header API key), guard endpoints.
3. embeddings.py — wrap embedder cache writes with a thread lock.
4. storage/sqlite_graph.py — use a connection-per-thread strategy or explicit locks for writes.
5. services/graph.py — replace `_build_graph()` calls with a cached summary updated on writes (or maintain a lightweight side-index).

Document location
-----------------
This review is saved at: docs/reviews/architecture_critical_review.md

How to use this file
--------------------
- Create issues from each prioritized checklist item.
- For each issue, author TDD-style tests that fail on current master.
- Implement fixes in small commits with descriptive conventional commit messages.
- Re-run benchmarks only after correctness fixes are in place; avoid benchmarking while changing embedding defaults.

If you want, I can now:
- Create a checklist of GitHub issues from the prioritized items.
- Generate failing unit tests (TDD) for the highest-priority items (drawer ID collision, embedder cache concurrency, sync auth).
- Draft PRs with the minimal fixes and tests.


End of document.
