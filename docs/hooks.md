# Hooks

SwampCastle ships hook logic for session checkpointing and pre-compaction saves.

The implementation lives in `swampcastle.hooks_cli`.

## Supported harnesses

Current built-in harness names:
- `claude-code`
- `codex`

The hook parser does **not** currently accept `gemini` as a built-in harness name.

## Supported hook names

- `session-start`
- `stop`
- `precompact`

## Internal CLI bridge

```bash
SWAMPCASTLE_INTERNAL=1 swampcastle hook run --hook stop --harness claude-code
```

This command reads JSON from stdin and prints JSON to stdout.

Example:

```bash
echo '{"session_id":"abc","stop_hook_active":false,"transcript_path":"/tmp/session.jsonl"}' \
  | SWAMPCASTLE_INTERNAL=1 swampcastle hook run --hook stop --harness claude-code
```

## What the hooks do

### stop

- counts human messages in the transcript
- blocks every `SAVE_INTERVAL` messages
- starts a background conversation ingest for the active `transcript_path` when it exists
- returns a reason instructing the assistant to save key context

### precompact

- runs synchronous conversation ingest for the active `transcript_path` when it exists
- always blocks
- tells the assistant to save everything before context is compacted

### session-start

- injects the `status` digest into the session as `additionalContext`
  (Claude Code `SessionStart`, matcher `startup|resume|clear|compact`; the
  pi extension injects the same text as a persistent message on the first
  `before_agent_start`)
- passes the harness `cwd` as the digest's `project_dir` scope
- serves a per-project cached digest from
  `~/.swampcastle/hook_state/digest/`; a cache older than 5 minutes is
  still served, with a detached `hook refresh-digest` rebuild for the next
  session; a cold cache builds synchronously once (~20s on a large castle)

## Hook state

State is stored under:

```text
~/.swampcastle/hook_state/
```

That directory keeps:
- per-session save checkpoints
- `hook.log`

## Auto-ingest

The hooks now use two optional ingest inputs.

### Active transcript
If the harness passes a readable `transcript_path`, the hooks ingest that exact transcript in conversation mode:

```bash
python -m swampcastle mine /path/to/session.jsonl --mode convos
```

### Legacy project source directory
The hook code still honors the legacy environment variable:

```text
MEMPAL_DIR
```

If set to a directory, the hooks also ingest that directory. The name is legacy, but it is still what the current code reads.

Important: `transcript_path` and `MEMPAL_DIR` are **additive**. If both are present, both ingest paths run.

## Python API

```python
from swampcastle.hooks_cli import run_hook

run_hook("stop", "claude-code")
```

## Expected input shape

The hook parser looks for:

| Field | Meaning |
|---|---|
| `session_id` | unique session identifier |
| `stop_hook_active` | loop-prevention flag |
| `transcript_path` | path to the transcript file |
| `cwd` | working directory; scopes the session-start digest |

## Debugging

Check the log file:

```bash
cat ~/.swampcastle/hook_state/hook.log
```
