# SwampCastle Evolution Roadmap

*Destination artifact of the [wayfinder map](http://192.168.129.37:30008/minder/swampcastle/issues/1), assembled 2026-07-10 from the decision tickets ([roadmap assembly](http://192.168.129.37:30008/minder/swampcastle/issues/13)). Each decision's full detail lives in its ticket's resolution comment — this document orders the work, it does not restate the designs.*

Decision tickets: [ingest/freshness #6](http://192.168.129.37:30008/minder/swampcastle/issues/6) · [retrieval #7](http://192.168.129.37:30008/minder/swampcastle/issues/7) · [curation #8](http://192.168.129.37:30008/minder/swampcastle/issues/8) · [protocol adherence #9](http://192.168.129.37:30008/minder/swampcastle/issues/9) · [sync #10](http://192.168.129.37:30008/minder/swampcastle/issues/10) · [upstream relationship #11](http://192.168.129.37:30008/minder/swampcastle/issues/11) · [retrieval benchmark #12](http://192.168.129.37:30008/minder/swampcastle/issues/12)

## Standing rules

- **Milestone step zero** ([#11](http://192.168.129.37:30008/minder/swampcastle/issues/11)): before starting a milestone, re-check MemPalace upstream's current take on that area only (`docs/research/mempalace-delta.md` is the living shopping list; `mempalace` remote stays wired). Ideas port, commits never.
- **Lazy tickets**: Gitea (Kuferek) execution issues are created per-milestone when that milestone starts — not in advance.
- **Contributions upstream**: opportunistic and small only (e.g. Polish entity locale, isolated fixes); no compatibility commitment.

## Milestone A — Freshness / ingest ([#6](http://192.168.129.37:30008/minder/swampcastle/issues/6))

The observed pain: a five-week-stale palace. Memory that isn't written makes everything downstream moot.

1. **Packaging/install decision** (first item — `install-hooks` forces it): pipx vs `uv tool`, Python 3.14 wheel risk, hook interpreter/venv resolution (upstream's pipx-aware pattern applies). Decided in-context here.
2. pi JSONL parser in `mining/normalize.py` (upstream has one — port the concept).
3. `install-hooks` command: session-end/precompact ingest hooks for pi + Claude Code.
4. Periodic idempotent sweep (systemd timer, ~6h) over both transcript directories.
5. Thin ingest path: chunk + embed + timestamps + mechanical routing; no LLM, never blocks.
6. Ingest-correctness audit against the upstream bug ledger (delta report §4).
7. Wayfinder-tracker source adapter (forge-agnostic, gated on `wayfinder:map` label detection).

Freshness SLO: next-session retrievability; sweep bounds worst-case staleness at hours.

## Milestone B — Protocol adherence ([#9](http://192.168.129.37:30008/minder/swampcastle/issues/9))

1. `status` digest redesign: hard cap (≤200 lines / 25KB), core-memory blocks, staleness flags, client-agnostic tool names.
2. Protocol text migration to MCP server `instructions` + ordering language in tool descriptions.
3. SessionStart injection hook (Claude Code matchers `startup|resume|clear|compact`; pi equivalent) — extends A's `install-hooks`.
4. `checkpoint` batch tool + enumerated write-trigger taxonomy + Stop-hook nudge.
5. Audit-service instrumentation: per-session consult/write/ordering metrics (report rollup lands in D's nightly job).

## Milestone C — Retrieval core ([#7](http://192.168.129.37:30008/minder/swampcastle/issues/7), [#12](http://192.168.129.37:30008/minder/swampcastle/issues/12))

**Hard constraint: re-embed migration lands before the FTS index build — one rebuild, not two.**

1. embeddinggemma-300m default + one-shot re-embed of all drawers + fingerprint migration.
2. Native FTS per backend (LanceDB tantivy BM25 / Postgres tsvector; in-memory keeps scan) + RRF fusion. Retires the 5K-cap token-overlap scan.
3. Rule-based temporal query parser (timestamp filter/boost); opt-in local-LLM tier reusing D's endpoint config.
4. Fused path becomes THE search; `hybrid`/`lexical_rerank` flags deprecated to no-ops for one release.
5. **Benchmark harness alongside, advisory** ([#12](http://192.168.129.37:30008/minder/swampcastle/issues/12)): LongMemEval slice ingested via the normal pipeline + ~15–25-query Polish/temporal probe set on a frozen snapshot; recall@10 + MRR per ability label; reuses `tests/benchmarks/report.py` plumbing.

## Milestone D — Curation / consolidation ([#8](http://192.168.129.37:30008/minder/swampcastle/issues/8))

1. `article` RecordKind + wiki directory + schema file (citations mandatory, size-capped rethink rewrites, edits-as-commits).
2. Bi-temporal KG columns migration; dynamics columns (`strength`, `stability`, `last_activated`, `access_count`) on edges and records + access tracking in search/traverse.
3. Sweep enrichment phase (near-line, new records only): fact-augmented retrieval keys, importance scores, rule-based KG proposals.
4. Nightly batch: contradiction reconciliation (tiered autonomy, never-delete invalidation), article creation/update, wiki lint, decay bookkeeping — plus B's adherence report rollup.
5. Local structured-output LLM endpoint config + no-LLM degraded mode.
6. **Benchmark flips advisory → per-slice CI gate** once C's baseline stabilizes.

## Milestone E — Graph channel ([#7](http://192.168.129.37:30008/minder/swampcastle/issues/7))

**Hard constraint: after D — PPR needs the enrichment pipeline to populate the KG (19 triples at decision time).**

1. PPR over the KG as the third RRF channel (HippoRAG 2 pattern), auto-enabled past a size/coverage threshold; below it, dense+lexical only.

## Milestone F — Sync ([#10](http://192.168.129.37:30008/minder/swampcastle/issues/10))

Hub-and-spoke: always-on LAN hub runs `garrison` + all maintenance + the LLM endpoint; spokes do thin capture.

**Hard constraint: the embedder fingerprint handshake lands before sync re-enables after C's re-embed.**

1. HLC timestamps replace wall-clock LWW comparison (node_id tiebreak stays).
2. KG sync metadata (node_id/seq) + transport through push/pull.
3. Tombstone propagation with all-nodes-seen GC gate.
4. Mandatory bearer auth (garrison refuses to start without); TLS stays the LAN/Tailscale boundary.
5. Snapshot + tail bootstrap for new/corrupt spokes.
6. Embedder fingerprint handshake.
7. Storage conformance suite (all three backends) + local write queue for concurrent same-machine writers.
8. Hub-hosted canonical wiki git remote; nightly job pulls before running; same-page collisions: human wins.

Out of scope: encryption-at-rest (single-user LAN).
