# MemPalace Upstream Delta — What Is Worth Pulling

*Research asset for the wayfinder ticket [MemPalace upstream delta: what is worth pulling](http://192.168.129.37:30008/minder/swampcastle/issues/4). Researched 2026-07-10.*

## Scope and method

SwampCastle forked from MemPalace at `b57c1603` (v3.1.0-22). Upstream (`mempalace` remote) is now at **v3.5.0** — 1,227 commits ahead of the fork point; SwampCastle added 199 commits of its own, including the full v4 rebuild (Castle services, LanceDB/Postgres storage ABCs, sync engine, unified KG, typed records, audit overlay). Three parallel readings fed this report: the upstream CHANGELOG (3.2.0 → 3.5.0), upstream RFCs and feature branches, and a baseline of what SwampCastle already has.

**Rule applied throughout:** upstream fixes to ChromaDB internals (HNSW quarantine, `repair --mode from-sqlite`, seq-id blob repair, chromadb pins — several dozen items) are **irrelevant**: SwampCastle replaced ChromaDB with LanceDB. What survives is conceptual/architectural work and correctness fixes to logic SwampCastle kept.

## Verdicts at a glance

| # | Pull | Pain addressed | Effort | Verdict |
|---|------|----------------|--------|---------|
| 1 | Hallways + Hebbian/Ebbinghaus dynamics | retrieval, curation | high | **Pull concept**, reimplement on unified KG |
| 2 | Multilingual default embedder (embeddinggemma-300m) | retrieval | low | **Pull** |
| 3 | Real BM25/FTS hybrid search | retrieval | medium | **Pull approach** — current full-scan lexical won't scale |
| 4 | Ingest-correctness fix audit (chunking/truncation/dedup) | ingest | medium | **Audit against checklist** |
| 5 | `checkpoint` batch-save MCP tool | protocol | low | **Pull** |
| 6 | `delete_by_source` + `source_file` search filter | curation, retrieval | low | **Pull** |
| 7 | MCP agent-ergonomics hardening batch | protocol | low | **Audit against checklist** |
| 8 | Corpus-origin Pass-0 detection | ingest, curation | medium | **Pull selectively** |
| 9 | Entity-pipeline maturity (COCA filter, compound lexicon, local-LLM refine) | curation | medium | **Pull** — unblocks re-wiring entity detection |
| 10 | HTTP MCP transport + write-queue daemon + replicated-palace RFC | sync scope | — | **Reference material** for the sync decision |
| 11 | RFC-001/002 plugin contracts (conformance suite, maintenance hooks) | robustness | medium | **Pull pieces** |
| 12 | Zero-config interpreter resolution for hooks | ingest | low | **Pull** |
| 13 | Privacy consent/warning gates for external LLMs | — | low | **Defer** until LLM-backed curation lands |

## The pulls in detail

### 1. Hallways + living-memory dynamics — the biggest conceptual pull

Upstream's most interesting post-fork work (merged, 3.3.6): **hallways** are within-wing edges auto-materialized from entity co-occurrence across drawers (`Wing → entity-tagged Drawers → Hallways → cross-wing Tunnels`); tunnels get auto-promoted when the same entity spans wings. On top sits `dynamics.py`: every hallway/tunnel carries `strength`, `stability`, `last_activated`, `access_count` — strength grows by Hebbian potentiation on co-access, fades by Ebbinghaus exponential decay (floored, never zero), stability grows via spaced reinforcement (Cepeda).

SwampCastle has curated tunnels (`GraphService.compute_curated_tunnels`) and a unified KG in LanceDB/SQLite/Postgres tables, but **no automatic edge formation and no usage dynamics** — the graph only knows what was explicitly added or curated. The dynamics answer the *curation/rot* pain (stale knowledge fades instead of accumulating) and the *retrieval* pain (usage-weighted ranking of graph hops).

**Do not port the implementation** — upstream persists hallways to a JSON sidecar file; SwampCastle should model them as first-class edges in its unified KG with the dynamics fields as columns. Pull the concept and the decay formulas.

### 2. Multilingual embedding default — cheapest big retrieval win

Upstream 3.3.6 replaced English-only MiniLM with **embeddinggemma-300m ONNX (q8, MRL-truncated to 384d)** as the default: cross-lingual cosine went 0.35 → 0.88, and it is dimension-compatible with existing 384d collections. SwampCastle's default is still `all-MiniLM-L6-v2` — English-only, while its palace holds Polish-and-English content. SwampCastle already has the machinery to make this painless: pluggable embedders, embedder fingerprints, and `swampcastle reindex`. Pull: add the model to the ONNX embedder aliases, benchmark, consider flipping the default.

### 3. Real lexical search — the scan cap is a live problem

Upstream built a real **BM25 hybrid** path (SQLite FTS5-backed, closets as a compact searchable pointer index, CLI surfacing `cosine=`/`bm25=` scores) plus **drawer-grep** (best chunk + adjacent-context drawers) and **virtual line numbers with surgical pointers** (closet pointers cite exact line ranges).

SwampCastle's hybrid mode (`retrieval/hybrid.py`) is honest about being an interim step: lexical candidates come from a **full collection scan capped at 5,000 records** with a token-coverage score — the live palace has **56K drawers**, so lexical recall silently misses ~90% of the collection. Pull the *approach*: a persistent lexical index per backend (SQLite FTS5 for local, Postgres full-text for server; Lance's native FTS is also a candidate), keeping SwampCastle's merge/rerank layer. The closet-pointer idea overlaps with SwampCastle's existing catalog cards — extend those rather than resurrect closets.

### 4. Ingest-correctness fixes — audit the v4 miner against upstream's bug ledger

Upstream fixed a series of **silent data-loss bugs** in mining logic that predates the fork's rewrite — some may have been reintroduced or never present; each needs a check against `swampcastle/mining/`:

- Unchunked content embedded in three upsert paths, truncating at the token limit (#1540)
- Paragraph chunker emitting chunks exceeding the embedder window (#1538); per-file chunk cap dropping transcript tails (#1554)
- 8-line AI-response truncation in convo mining (#708); full AI response stored (#695)
- `.jsonl` files silently dropped over 10 MB (#998) + message-level idempotent **sweeper** safety net (`mempalace sweep`)
- Room misrouting via substring matching — `views/…` filed into an `interviews` room (#1004, separator-bounded `_name_matches`)
- Drawer IDs hashed over full content for stable re-mines (#716); epsilon mtime comparison (#610); mode-scoped dedup (#1528)
- Noise stripping of system tags/hook chrome before filing (#785)

Also worth pulling outright: **SessionEnd final-mine** (#1814 — capture the last exchanges instead of waiting for the next save nudge; SwampCastle's `hook_stop` has the threshold-based path already) and new **transcript parsers** (Gemini CLI, Continue.dev, **Pi agent JSONL** — pi is the user's daily driver; check whether SwampCastle's normalizer already covers pi natively).

### 5–7. Small, high-leverage MCP pulls

- **`checkpoint` batch-save tool** (#1851): one MCP round-trip files N drawers + a diary entry, idempotent dedup path. Directly serves the *protocol adherence* pain — agents are likelier to file a session as one call than as ten.
- **`delete_by_source`** (#1722, dry-run by default, blast-radius report) and **`source_file` filter on search** (#1815): the recourse for benchmark/eval files drowning out real memory. SwampCastle has typed records + tombstones — implement as tombstone-first bulk operation.
- **Agent-ergonomics hardening batch** (audit checklist): empty string = "no filter" (#1097 — LLMs fill every optional param), case-insensitive diary agent match (#1243), ISO-temporal validation with clear errors on KG tools (#1164), structured `-32602` errors instead of tracebacks (#1500), stdout→stderr redirect during import so library logging can't corrupt JSON-RPC (#225 — verify SwampCastle's server does this), tunnel-creation errors propagated not swallowed (#1546). Each is small; together they are the difference between an agent that retries correctly and one that gives up.

### 8–9. Entity and origin intelligence — the path to re-wiring entity detection

SwampCastle deliberately unwired entity detection from setup (`8e9284b`) because it dumped raw heuristics at users. Upstream spent 3.3.x making exactly that viable:

- **COCA content-word filter** (#1605): bundled wordlist keeps "system/user/memory" out of the people registry.
- **Known-systems compound lexicon**: multi-word product names matched as compounds.
- **`llm_refine`**: opt-in reclassification of candidates into PERSON/PROJECT/TOPIC/COMMON_WORD — **local-first (Ollama) by default**, batched, never touches the raw corpus. Fits SwampCastle's "local LLM OK" constraint exactly.
- **Corpus-origin Pass-0** (merged): cheap heuristic + optional LLM tier that detects "this corpus is an AI dialogue" and extracts agent persona names, so downstream classification doesn't mistake agent personas for humans. SwampCastle's audit overlay has origin *manifests* but not this *semantic* detection; its wizard-based identity registry covers the user side, not the agent-persona side.
- i18n: upstream has 15+ locales but **no Polish** — if entity detection is re-wired, a `pl.json` locale is a SwampCastle-side addition worth making.

These matter beyond the registry: entity tags on drawers are the substrate hallways (#1) are built from.

### 10. Sync/server: reference material, not a pull

Three upstream artifacts bear directly on the open sync-guarantees decision, none mergeable as-is:

- **HTTP MCP transport** (3.5.0, merged): loopback-bound JSON-RPC at `POST /mcp`, Host/Origin DNS-rebind guards, bearer token, 16 MiB cap. SwampCastle's server mode currently syncs *state*; upstream's answer is remote *access*. Both models are on the table for the decision.
- **Local write-queue daemon** (3.5.0, merged): serializes concurrent writers through one process — relevant the moment pi and Claude Code both write.
- **Replicated-palace RFC-004** (draft, unmerged): N equal replicas, agents always talk to localhost, HLC-ordered append-only op-log, LWW conflicts, tombstone propagation, hub demoted to rendezvous. This is a *direct competitor design* to SwampCastle's existing node_id/seq/version-vector sync engine — the sync decision ticket should judge SwampCastle's engine against RFC-004's requirement list (R0–R8: offline capture, partition resolution, snapshot+tail rejoin, encryption-at-rest…).

### 11–12. Contracts and plumbing

- **RFC-001** (accepted, implemented upstream): SwampCastle already has equivalent storage ABCs. Worth pulling: the **conformance test suite** idea (one test suite all backends must pass — SwampCastle has three backends and pg integration tests, but no shared contract suite), **capability tokens**, and **observable maintenance hooks** (`run_maintenance(kind)` — upstream's concrete win is a pgvector build-index-once path; SwampCastle's Postgres backend has the same need).
- **RFC-002** (draft): SwampCastle's internal `BaseSourceAdapter` seam matches the spirit. Worth stealing: **incremental-ingest cursor** (`is_current()`), **declared-transformation model** (replaces the informal "verbatim" promise with a verifiable one), and per-adapter **privacy class**.
- **Zero-config interpreter resolution** (`mempal_resolve_python`, 3.4.1): derives Python from the console-script shebang so **pipx/uv-tool installs don't silently never mine** — SwampCastle is installed via pipx; check `hooks/` for this failure mode.

### 13. Deferred

Privacy consent gates (external-LLM warning, env-var-credential consent, Tailscale CGNAT-as-local) are init-time controls on upstream's LLM client. SwampCastle core has no LLM client today; adopt these patterns when LLM-backed curation (#9 above, curation ticket) introduces one. Cursor/Antigravity IDE plugins: out of current scope (clients are pi + Claude Code).

## What is explicitly not worth pulling

- All ChromaDB lifecycle/repair/quarantine work (~40 changelog items) — no ChromaDB in v4.
- Closets as a storage tier — SwampCastle demoted them deliberately; catalog cards cover the niche.
- The `mempalace migrate` ChromaDB-version tooling — SwampCastle keeps `[chroma]` extra only for legacy migration.
- VitePress site, scam-alert notices, GitHub Pages plumbing — upstream-project-specific.

## Suggested consumption by the open decision tickets

- **Retrieval quality** ticket: pulls #2 (embedder), #3 (BM25/FTS), #1 (dynamics-weighted ranking), plus the 5,000-record scan-cap finding.
- **Ingest/freshness** ticket: pulls #4 (audit), #12 (pipx hook resolution), SessionEnd mine, pi parser check.
- **Curation/consolidation** ticket: pulls #1 (decay), #6 (bulk cleanup), #8–9 (origin + entity intelligence as the substrate for distillation).
- **Protocol adherence** ticket: pulls #5 (checkpoint), #7 (ergonomics batch).
- **Sync guarantees** ticket: item #10 wholesale, especially RFC-004's R0–R8 as an evaluation rubric.
- **Upstream relationship** (new): upstream is fast-moving (3 releases/quarter) and still ChromaDB-centric at its core; wholesale merging is impossible post-v4-rebuild. The realistic modes are cherry-pick-by-concept (this document as the shopping list) or full divergence with periodic delta refreshes.
