# Ingest-Area Port Notes — MemPalace Upstream

*Research asset for the wayfinder ticket [Refresh the upstream delta for the ingest area and write port notes](http://192.168.129.37:30008/minder/swampcastle/issues/15) (map [#14](http://192.168.129.37:30008/minder/swampcastle/issues/14), milestone A step zero). Researched 2026-07-10. Complements [mempalace-delta.md](mempalace-delta.md) — this zooms its ingest verdicts (#4, #12, SessionEnd mine, pi parser) to port level.*

## Upstream state: nothing new

Upstream is **still v3.5.0**, tip `5cbc37e` (2026-06-28) — unchanged since the delta report; the only post-report activity is a dependabot branch. The delta report's ingest-area verdicts stand as written. (The local `v4.x` tags are SwampCastle's own rebuild tags, not upstream's.)

## 1. Pi JSONL parser — port near-verbatim

**Where:** `mempalace/normalize.py` `_try_pi_jsonl` (~45 lines, line 369 at `mempalace/main`), wired into the JSONL dispatch chain in `normalize()`. Tests in upstream `tests/test_normalize.py`.

**Approach:** line-by-line JSON parse; **gate on a `{"type": "session", "version": ...}` header line AND ≥2 extracted messages** — this double gate is what keeps it from false-positiving against other JSONL dialects (and keeps them from claiming pi files). Only `{"type": "message"}` entries are read; `message.role` must be `user`/`assistant` (role `toolResult` and event types like `model_change` fall through the type filter); text comes via `_extract_content`, which collects only `type == "text"` blocks — thinking blocks are skipped for free.

**Port cost is minimal:** our `swampcastle/mining/normalize.py` already has both helpers the function leans on (`_extract_content` line 273, `_messages_to_transcript`). The port is one ~40-line function plus a dispatch entry next to `_try_claude_code_jsonl`/`_try_codex_jsonl`.

**Verified against real local data** (schema matches upstream's expectations):

- Sessions live at **`~/.pi/agent/sessions/{escaped-cwd}/{ISO-timestamp}_{uuid}.jsonl`** on this machine — *not* the `~/.config/pi/agent/sessions/` path upstream's docstring claims. The sweep/hook tickets must use `~/.pi/agent/sessions/`.
- Header line: `{type: session, version, id, timestamp, cwd}`. Message lines: `{type: message, id, parentId, timestamp, message: {role, content}}` with content as a block list. Extra event types observed: `model_change`, `thinking_level_change`.
- **Local corpus: 897 session files, 816 MB, 14 files over 10 MB (largest 63 MB)** — see the #998 size-cap item below.

**Known caveat to accept for v1:** pi history is tree-structured via `parentId`; upstream reads it linearly, so abandoned branches (retries, forks) interleave into the transcript. Upstream ships this. If it ever matters, walk the `parentId` chain back from the final leaf instead.

Per-entry `timestamp` and the session `id` are exactly what the sweep cursor needs (§3).

## 2. Hook interpreter resolution — the pipx-aware pattern

Upstream has two generations; port the second.

- **Basic** (`hooks/cursor/lib/common.sh:45`): `$MEMPAL_PYTHON` override → first `python3` on PATH → bare `python3`. This is the one that silently never mines under pipx/uv-tool when the hook PATH lacks the venv.
- **Pipx-aware** (`hooks/antigravity/lib/common.sh:83`, `mempal_resolve_python`): inserts a step that **derives the interpreter from the console-script shebang** — `command -v mempalace-mcp`/`mempalace`, read the `#!` line, accept only an executable whose basename matches `python*` (explicitly skipping `#!/usr/bin/env python` wrappers, which yield `/usr/bin/env`). Deliberately **no `import` probe at resolve time** — the ONNX/DB cold-start cost stays off the hook foreground; a backgrounded `--version` probe downstream is the safety net.
- The claude-code session-end hook (`hooks/mempal_session_end_hook.sh`) uses a simpler ladder that tries the **console script itself first** (`command -v mempalace` → `exec mempalace hook run …`), then the python fallbacks. Fire-and-forget shape: read stdin payload, background the real work, `disown`, print `{}` immediately so the harness never blocks.

**Port shape for us:** console-script-first (`command -v swampcastle`) covers the common case under *both* pipx and `uv tool` (each puts console scripts on PATH); shebang derivation is the fallback for stripped-PATH hook environments. This makes the resolution ladder **packaging-agnostic — useful input for the packaging decision ([#16](http://192.168.129.37:30008/minder/swampcastle/issues/16)), which it survives either way.**

**SessionEnd final-mine (#1814):** upstream added a `session-end` hook that mines the tail exchanges at session close instead of waiting for the next-session nudge. Our `swampcastle/hooks_cli.py` has `stop`/`session-start`/`precompact` for `SUPPORTED_HARNESSES = {"claude-code", "codex"}` (line 154) — **no `session-end`, no pi harness**. The install-hooks ticket ([#19](http://192.168.129.37:30008/minder/swampcastle/issues/19)) extends both; how pi exposes hooks is that ticket's own homework.

## 3. Sweeper — the idempotency recipe

`mempalace/sweeper.py` (347 lines) is the reference for the sweep ticket ([#18](http://192.168.129.37:30008/minder/swampcastle/issues/18)). The algorithm, per session file:

1. `cursor = max(timestamp)` of sweeper-written drawers for this `session_id` (queried from the store, not a state file);
2. for each user/assistant message: skip if `timestamp < cursor` (strict `<`, so max-timestamp ties re-attempt and dedup on ID);
3. upsert a drawer with a **deterministic ID hashed from `(session_id, message_uuid)`**, existence-prechecked before counting.

Idempotent on its own writes, resume-safe after a crash, no size caps (one exchange per drawer). **Its admitted weakness:** it doesn't coordinate with the file-level miners — they don't stamp `session_id`/`timestamp`/`ingest_mode`, so the same content can land twice under different IDs. Upstream stamps `ingest_mode` (`"registry"`, `"convos"`, see `convo_miner.py:98,441`) as the beginning of a fix. **Our sweep should design uniform provenance metadata (session_id, message timestamp, ingest_mode) across hook-path and sweep-path writes from day one**, not inherit the split.

## 4. Bug-ledger audit pointers (for [#20](http://192.168.129.37:30008/minder/swampcastle/issues/20))

The checklist itself is delta report §4; upstream implementation loci for the non-obvious ones:

- **Chunker guards** (#1538/#1554): `mempalace/convo_miner.py` `_chunk_by_exchange`/`_chunk_by_paragraph`/`_emit_bounded` (~lines 142–250) — bounded emission instead of per-file chunk caps, explicit guards against non-positive `chunk_size` looping forever.
- **Mode-scoped dedup** (#1528): the `ingest_mode` metadata stamp, as above.
- **10 MB `.jsonl` drop** (#998): directly live here — **14 real pi session files exceed 10 MB**. Whatever cap our miner has must page or stream, not skip.
- **Noise stripping** (#785): upstream `normalize.py` opens with a `strip_noise` pass (system-tag regexes, `_NOISE_LINE_PREFIXES`, collapsed-`… +N lines` pattern). **Our `mining/normalize.py` has no equivalent — one confirmed gap already**, found while comparing; the audit should treat it as a to-port item, not just a check.
- Audit surface on our side: `swampcastle/mining/` (`miner.py`, `convo.py`, `normalize.py`, `adapters/`).
