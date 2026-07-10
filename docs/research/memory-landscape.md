# Agent Long-Term Memory Landscape — Ideas Worth Adopting

*Research asset for the wayfinder ticket [Survey agent long-term memory designs](http://192.168.129.37:30008/minder/swampcastle/issues/5). Researched 2026-07-10 by five parallel readings: Karpathy's LLM Wiki, Letta/MemGPT, mem0, Zep/Graphiti, the academic landscape (A-MEM, HippoRAG, generative-agents reflection, MemOS, Memp, LongMemEval), and production protocol-adherence practice (Claude Code, Anthropic memory tool, ChatGPT memory, MCP memory servers).*

Evaluation frame: the four decided pain points — **freshness/ingest**, **retrieval quality**, **curation/rot**, **protocol adherence** — under the constraint *local-first, local LLM OK for maintenance jobs, no cloud API in core*.

## The headline

**SwampCastle's stack is already the shape the field converged on.** Verbatim drawers = the non-lossy episodic layer (Graphiti's episodes, HippoRAG's passages, Karpathy's immutable raw sources); the temporal KG with `valid_from/valid_to` = the semantic index (Graphiti's edges, HippoRAG's hippocampal graph); catalog cards/AAAK = the beginnings of a distilled layer. Nothing surveyed requires abandoning the architecture. What the survey supplies is (a) the *missing mechanisms* on each layer, (b) a clear division of labor — **LLM at write/maintenance time, never at read time** — and (c) the finding that protocol adherence is solved by harness machinery, not prompt text.

## Six load-bearing findings

### 1. Read-path: no LLM, three fused channels (retrieval quality)

Every serious system keeps reads model-free and fuses multiple recall channels:

- **Graphiti**: cosine + Okapi BM25 + breadth-first graph traversal, fused by RRF (or MMR / node-distance-from-focal-entity / mention-frequency — all LLM-free). Zep: LongMemEval 71.2% with context reduced 115k → 1.6k tokens.
- **HippoRAG** ([2405.14831](https://arxiv.org/abs/2405.14831)): Personalized PageRank seeded on query entities, propagated over the KG to rank passages — single-step multi-hop retrieval, pure graph math at query time, 10–30× cheaper than iterative retrieval. HippoRAG 2's correction: keep passages linked into the graph and blend PPR with plain vector similarity, or simple factual queries regress.
- **LongMemEval**'s measured fixes ([2410.10813](https://arxiv.org/abs/2410.10813)): index at round/exchange granularity (not whole sessions); **fact-augmented key expansion** — LLM at *ingest* emits facts/keywords stored as extra retrieval keys pointing at the verbatim chunk (+4% recall, +5% accuracy); **time-aware query expansion** — one small LLM call resolves the query's implied time window, then filter by timestamp (+7–11% recall). SwampCastle's temporal KG makes the last one unusually cheap.

Direct SwampCastle mapping: replace the 5K-record lexical scan with a real FTS/BM25 index (LanceDB has native FTS; SQLite FTS5; Postgres full-text), add RRF fusion of dense + lexical + graph-hop lists, and consider PPR over `kg_triples` seeded from query entities. All local, all cheap.

### 2. Write-path: extract-then-reconcile, bounded candidates (freshness + curation)

- **mem0** ([2504.19413](https://arxiv.org/abs/2504.19413)): ~2 LLM calls per write — extract candidate facts (context: latest exchange + rolling summary + last 10 messages), then one batched call that sees each candidate with its top-10 semantic neighbors and emits ADD/UPDATE/DELETE/NOOP. The trick that bounds cost: **the neighborhood is the only conflict-candidate set**. Exact-dup content hashing runs before any LLM. mem0's own V3 retreat is instructive: destructive UPDATE/DELETE lost information, so they moved to additive-only with temporal grounding — validating SwampCastle's existing invalidation design.
- **Graphiti**: contradiction checking scoped to **edges sharing the same entity pair** with temporal overlap; on contradiction, **set `t_invalid`, never delete**. Bi-temporality (valid time *and* transaction time) distinguishes "stopped being true" from "we learned it was wrong". Caveat for local LLMs: Graphiti's write path is ~5–15 LLM calls per episode and requires structured-output-capable models — small local models break the schemas. Budget: mem0's 2-call shape feeding Graphiti's invalidation semantics.
- **LongMemEval's failure taxonomy** is the cautionary tale: ChatGPT −37% vs offline reading because it **overwrites older information as sessions accumulate** (over-eager consolidation = the rot), and Coze −64% because it **fails to record indirectly-presented information** (ingest miss). Loss, not clutter, is the dominant production failure. Decay should demote and archive; only LLM-arbitrated *supersession* (with provenance) should ever hide a fact.

### 3. Consolidation is a sleep-time job, not inline work (curation)

The strongest cross-system convergence:

- **Letta sleep-time compute** ([2504.13171](https://arxiv.org/abs/2504.13171)): a *separate* background agent holds the memory-editing tools; the chat agent literally cannot corrupt core memory. It runs every N steps / at idle, turning "raw context into learned context" — dedup, contradiction resolution, promotion of hot facts. ~5× less query-time compute for equal accuracy. Cheap models suffice ("consolidation, not complex reasoning").
- **Generative agents** ([2304.03442](https://arxiv.org/abs/2304.03442)): reflection triggered by an **importance accumulator** (LLM scores each memory 1–10 at write; when the running sum passes a threshold, a batch job generates salient questions, retrieves against them, and writes back *cited* insight notes). Importance scoring's best use is triggering consolidation, not ranking.
- **OpenAI's "Dreaming"**: write synthesis moved to an async background process reading whole conversations — adherence solved by removing the write from the live loop entirely.
- **MemoryBank** ([2305.10250](https://arxiv.org/abs/2305.10250)): Ebbinghaus strength decay + reinforcement-on-recall — pure bookkeeping, zero LLM. Convergent with the MemPalace hallway/tunnel dynamics already identified in the delta research (`docs/research/mempalace-delta.md`).
- **A-MEM** ([2502.12110](https://arxiv.org/abs/2502.12110)): the one system that retroactively *rewrites* old memories' metadata on new arrivals. Verdict from the field: riskiest mechanism surveyed (compounding LLM edits = drift); prefer additive reflections with provenance links until evaluation gates exist.

SwampCastle fit: this is exactly what `DistillEngine`/`ReforgeEngine` and the audit overlay want to become — a local-LLM maintenance daemon (cron/session-end) that runs distillation, contradiction arbitration (KG invalidation, not deletion), and decay bookkeeping, with every product auditable and re-derivable from drawers.

### 4. The wiki/distilled-article layer earns its place — with guardrails (curation + retrieval)

Karpathy's LLM Wiki ([gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)) contributes the piece chunks+triples genuinely lack: **"what do we currently believe about X, all sources considered"** — the materialized join over N drawers and M triples, computed once at maintenance time so query time is one page read. Key mechanisms to steal:

- **Three-layer contract**: immutable raw sources (= drawers) / LLM-owned wiki pages / a *schema* file defining page types, citation rules, and ingest fan-out. Articles must cite drawer IDs so every page is re-derivable — the main defense against the field's loudest critique (second-order "slop compounding").
- **Queries are writes**: good answers get filed back as pages instead of dying in chat history. This is the compounding loop.
- **Lint** as a bounded local-LLM job: contradictions, superseded claims, orphans, gaps — with the comparison set picked by KG adjacency (O(neighbors), not O(N²) page pairs).
- Field-tested limits (HN, one-month reports, "v2" gist): flat index breaks at ~200–500 documents (SwampCastle's search covers this); drift from under-updated cross-references is the primary failure mode (lint must be scheduled, not vibes); guarded writes — maintenance jobs propose, a validation step (citation check against drawers, KG consistency) gates the merge.

The open design question this feeds ticket-#8: whether articles are a new `RecordKind`, an extension of catalog cards, or a separate wiki tier. (The survey's evidence: keep typed data in the KG; articles hold the narrative residue that doesn't decompose into triples.)

### 5. Protocol adherence is an injection problem, not a prompting problem

The production hierarchy of reliability, top to bottom: **harness-enforced injection** (hooks, server-side prompt insertion, tool rules) → auto-added system-prompt protocol when the tool is present (Anthropic's memory tool injects *"ALWAYS VIEW YOUR MEMORY DIRECTORY BEFORE DOING ANYTHING ELSE… ASSUME INTERRUPTION"*) → user-installed protocol prompt (the MCP KG server is never called without it) → tool descriptions alone (documented to fail) → **a paragraph in a global AGENTS/CLAUDE file — SwampCastle's current tier, the weakest**. Claude Code's own docs concede CLAUDE.md gets "no guarantee of strict compliance."

Concrete upgrades for SwampCastle, in leverage order:

1. **SessionStart hook** (matchers `startup|resume|clear|compact`) that emits the `status` digest as `additionalContext` — the index is simply *there*, every session, including after compaction. The read step you cannot skip is the one that happens without the model. (pi equivalent: its hook/system-prompt surface.)
2. **`status` returns a capped index** (the 200-line/25KB precedent): digest + pointers, zoom via `search`/`kg_query`. Never the whole store.
3. **Protocol into tool descriptions and the MCP server `instructions` field** — these are always in context, unlike AGENTS.md paragraphs. Ordering language on `status` ("call first, before any task work"); **enumerated write-trigger taxonomies** on `add_drawer`/`diary` ("save when: a user correction; a command that worked; a debugging insight; a decision + rationale; a preference") — the enumerated taxonomy is what made the reference MCP KG server work at all.
4. **Write lifecycle anchors**: a Stop-hook nudge ("if this session produced a durable learning, record it"), plus **async Dreaming-style synthesis** — SwampCastle's transcript auto-ingest hooks already are this; the survey validates doubling down on mining-as-write-path over trusting live agents to file memories.
5. **Batch the write**: MemPalace's `checkpoint` tool (delta report) and Letta's leaderboard finding (penalize unnecessary tool calls; agents over-trigger single ops) agree — one "file this session" call beats ten `add_drawer` calls.
6. **Staleness structurally**: timestamps on everything (already present), `status` flags entries older than N months, tool descriptions instruct update-don't-accumulate.

### 6. Always-in-context blocks are the harness's property — approximate honestly

Letta's core memory blocks (labeled, size-capped, always-pinned, edited via `memory_rethink`) are the field's anti-rot core, but an MCP server **cannot pin content into a host's context** — that property belongs to the harness. The honest approximations: the SessionStart-hook injection above, MCP resources, and a `get_core_memory`-style block read in `status`. Worth adopting anyway: **hard character limits per distilled block** (memory cannot silently bloat) and **rethink = whole-block rewrite** (stale text is replaced, not accreted) as the contract for whatever SwampCastle's distilled layer becomes.

## Mechanisms menu (consolidated)

| Mechanism | Source | Pain | LLM cost | Verdict |
|---|---|---|---|---|
| FTS/BM25 index + RRF fusion of dense+lexical+graph | Graphiti, LongMemEval | retrieval | none at read | **Adopt** — replaces the 5K-scan defect |
| Personalized PageRank over KG, seeded from query entities | HippoRAG | retrieval (multi-hop) | none at read | **Adopt** — blend with vector sim per HippoRAG 2 |
| Fact-augmented key expansion at ingest | LongMemEval | retrieval | small, at ingest | **Adopt** |
| Time-aware query expansion → timestamp filter | LongMemEval | retrieval (temporal) | 1 small call/query (optional tier) | **Adopt** |
| Round/exchange-granularity indexing | LongMemEval | retrieval | none | **Adopt** — check current chunking |
| Extract-then-reconcile, neighbor-bounded (ADD/UPDATE/NOOP; no DELETE) | mem0 | freshness, curation | ~2 calls/write | **Adopt** for KG proposals pipeline |
| Contradiction → `valid_to` invalidation + transaction time | Graphiti | curation | scoped adjudication call | **Adopt** — extends existing `kg_invalidate` |
| Provenance edges: triples → source drawers | Graphiti, HippoRAG | curation, audit | none | **Adopt** |
| Sleep-time maintenance daemon (separate from live agents) | Letta, OpenAI Dreaming | curation, adherence | background, cheap model | **Adopt** — the umbrella for distill/lint/decay |
| Importance score (1–10 at write) as consolidation trigger | Generative agents | curation | 1 tiny call/write or batch | **Adopt** (trigger, not ranking) |
| Strength decay + reinforcement-on-recall (rank/demote, never delete) | MemoryBank, MemPalace dynamics | curation, retrieval | none (bookkeeping) | **Adopt** — converges with delta-report pull #1 |
| Distilled wiki/article layer: cited, linted, size-capped, rethink-rewritten | Karpathy, Letta blocks, LLM-Wiki v2 | curation, retrieval | background | **Adopt with guardrails** (design in ticket #8) |
| SessionStart/compact hook injection of `status` digest | Claude Code practice | adherence | none | **Adopt** — highest-leverage single change |
| Write-trigger taxonomy in tool descriptions + server `instructions` | MCP KG server, Anthropic memory tool | adherence | none | **Adopt** |
| `checkpoint` batch session-save | MemPalace, Letta leaderboard | adherence | none | **Adopt** (already in delta report) |
| Procedural memory class (scripts w/ deprecation) | Memp | adherence | background | **Consider later** — big-model-distills/small-model-consumes transfer result is relevant |
| A-MEM retroactive note rewriting | A-MEM | curation | 2–3 calls/write | **Reject for now** — drift risk without eval gates |
| MemOS parametric/KV-cache tiers | MemOS | — | research-grade | **Reject** — vocabulary useful, mechanism premature |
| Letta-style always-pinned blocks | Letta | adherence | — | **Approximate only** — harness owns the context |

## Consumption map for the unblocked decision tickets

- **Decide the ingest/freshness pipeline** (#6): finding 2 (extract-then-reconcile write budget; LongMemEval's "ingest miss" failure), finding 3 (async synthesis as the primary write path — validates hook-driven mining), fact-augmented key expansion at ingest, round-granularity chunking check.
- **Decide retrieval quality improvements** (#7): finding 1 wholesale + the mechanisms-menu retrieval rows; benchmark note — LongMemEval's ability taxonomy (esp. temporal reasoning and abstention) is the right rubric, but beware "benchmark theatre": retrieval-QA scores don't measure whether agents consult memory unprompted.
- **Decide curation/consolidation design** (#8): findings 3, 4, and the invalidation semantics of finding 2; the article-layer design question (RecordKind vs catalog-card extension vs wiki tier); decay-demotes-never-deletes; guarded writes with citation validation.
- **Decide the memory-use protocol** (#9): findings 5 and 6 wholesale; the reliability hierarchy is the organizing principle — decide per client (Claude Code has hooks; pi has its own surfaces) which tier each protocol step lands on.
- **Sync guarantees** (#10, unchanged): nothing here contradicts the delta report's RFC-004 rubric; Letta's shared-blocks last-write-wins punt is a warning, not a model.
