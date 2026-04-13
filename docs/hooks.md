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
- returns a reason instructing the assistant to save key context

### precompact

- always blocks
- tells the assistant to save everything before context is compacted

### session-start

- initializes state
- does not block

## Hook state

State is stored under:

```text
~/.swampcastle/hook_state/
```

That directory keeps:
- per-session save checkpoints
- `hook.log`

## Auto-ingest

The hook code still honors the legacy environment variable:

```text
MEMPAL_DIR
```

If set to a directory, the hooks try to run a background or synchronous ingest against that path. The name is legacy, but it is still what the current code reads.

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

## Debugging

Check the log file:

```bash
cat ~/.swampcastle/hook_state/hook.log
```
