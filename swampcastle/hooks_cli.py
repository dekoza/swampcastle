"""
Hook logic for SwampCastle — Python implementation of session-start, stop, and precompact hooks.

Reads JSON from stdin, outputs JSON to stdout.
Supported hooks: session-start, stop, precompact, session-end
Supported harnesses: claude-code, codex, pi (extensible to cursor, gemini, etc.)
"""

import json
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

SAVE_INTERVAL = 15
STATE_DIR = Path.home() / ".swampcastle" / "hook_state"

# A cached digest younger than this is served without spawning a refresh —
# concurrent session starts must not pile up 20s rebuild subprocesses.
DIGEST_REFRESH_SECONDS = 300

STOP_BLOCK_REASON = (
    "AUTO-SAVE checkpoint. Save key topics, decisions, quotes, and code "
    "from this session to your memory system. Organize into appropriate "
    "categories. Use verbatim quotes where possible. Continue conversation "
    "after saving."
)

PRECOMPACT_BLOCK_REASON = (
    "COMPACTION IMMINENT. Save ALL topics, decisions, quotes, code, and "
    "important context from this session to your memory system. Be thorough "
    "\u2014 after compaction, detailed context will be lost. Organize into "
    "appropriate categories. Use verbatim quotes where possible. Save "
    "everything, then allow compaction to proceed."
)


def _sanitize_session_id(session_id: str) -> str:
    """Only allow alnum, dash, underscore to prevent path traversal."""
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)
    return sanitized or "unknown"


def _count_human_messages(transcript_path: str) -> int:
    """Count human messages in a JSONL transcript, skipping command-messages."""
    path = Path(transcript_path).expanduser()
    if not path.is_file():
        return 0
    count = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    msg = entry.get("message", {})
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        content = msg.get("content", "")
                        if isinstance(content, str):
                            if "<command-message>" in content:
                                continue
                        elif isinstance(content, list):
                            text = " ".join(
                                b.get("text", "") for b in content if isinstance(b, dict)
                            )
                            if "<command-message>" in text:
                                continue
                        count += 1
                    # Also handle Codex CLI transcript format
                    # {"type": "event_msg", "payload": {"type": "user_message", "message": "..."}}
                    elif entry.get("type") == "event_msg":
                        payload = entry.get("payload", {})
                        if isinstance(payload, dict) and payload.get("type") == "user_message":
                            msg_text = payload.get("message", "")
                            if isinstance(msg_text, str) and "<command-message>" not in msg_text:
                                count += 1
                except (json.JSONDecodeError, AttributeError):
                    pass
    except OSError:
        return 0
    return count


def _log(message: str):
    """Append to hook state log file."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        log_path = STATE_DIR / "hook.log"
        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(log_path, "a") as f:
            f.write(f"[{timestamp}] {message}\n")
    except OSError:
        pass


def _output(data: dict):
    """Print JSON to stdout with consistent formatting (pretty-printed)."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _auto_ingest_commands(transcript_path: str = "") -> list[list[str]]:
    commands: list[list[str]] = []

    transcript = Path(transcript_path).expanduser()
    if transcript.is_file():
        commands.append(
            [
                sys.executable,
                "-m",
                "swampcastle",
                "mine",
                str(transcript),
                "--mode",
                "convos",
            ]
        )

    mempal_dir = os.environ.get("MEMPAL_DIR", "")
    if mempal_dir and os.path.isdir(mempal_dir):
        commands.append([sys.executable, "-m", "swampcastle", "mine", mempal_dir])

    return commands


def _maybe_auto_ingest(transcript_path: str = ""):
    """Run optional background ingest for the active transcript and legacy source dir."""
    commands = _auto_ingest_commands(transcript_path)
    if not commands:
        return

    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        log_path = STATE_DIR / "hook.log"
        with open(log_path, "a") as log_f:
            for command in commands:
                # start_new_session: the harness reaps the hook's process
                # group on cancellation/shutdown — a mine in the same group
                # dies with it before filing anything.
                subprocess.Popen(command, stdout=log_f, stderr=log_f, start_new_session=True)
    except OSError:
        pass


SUPPORTED_HARNESSES = {"claude-code", "codex", "pi"}


def _parse_harness_input(data: dict, harness: str) -> dict:
    """Parse stdin JSON according to the harness type."""
    if harness not in SUPPORTED_HARNESSES:
        print(f"Unknown harness: {harness}", file=sys.stderr)
        sys.exit(1)
    return {
        "session_id": _sanitize_session_id(str(data.get("session_id", "unknown"))),
        "stop_hook_active": data.get("stop_hook_active", False),
        "transcript_path": str(data.get("transcript_path", "")),
        "cwd": str(data.get("cwd", "")),
    }


def hook_stop(data: dict, harness: str):
    """Stop hook: block every N messages for auto-save."""
    parsed = _parse_harness_input(data, harness)
    session_id = parsed["session_id"]
    stop_hook_active = parsed["stop_hook_active"]
    transcript_path = parsed["transcript_path"]

    # If already in a save cycle, let through (infinite-loop prevention)
    if str(stop_hook_active).lower() in ("true", "1", "yes"):
        _output({})
        return

    # Count human messages
    exchange_count = _count_human_messages(transcript_path)

    # Track last save point
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    last_save_file = STATE_DIR / f"{session_id}_last_save"
    last_save = 0
    if last_save_file.is_file():
        try:
            last_save = int(last_save_file.read_text().strip())
        except (ValueError, OSError):
            last_save = 0

    since_last = exchange_count - last_save

    _log(f"Session {session_id}: {exchange_count} exchanges, {since_last} since last save")

    if since_last >= SAVE_INTERVAL and exchange_count > 0:
        # Update last save point
        try:
            last_save_file.write_text(str(exchange_count), encoding="utf-8")
        except OSError:
            pass

        _log(f"TRIGGERING SAVE at exchange {exchange_count}")

        # Optional: auto-ingest the active transcript and any legacy source dir.
        _maybe_auto_ingest(transcript_path)

        _output({"decision": "block", "reason": STOP_BLOCK_REASON})
    else:
        _output({})


def _digest_cache_path(project_dir: str) -> Path:
    """Per-project digest cache file under the hook state directory."""
    slug = re.sub(r"[^a-z0-9]+", "_", project_dir.lower()).strip("_") or "global"
    return STATE_DIR / "digest" / f"{slug}.md"


def _build_digest_text(project_dir: str) -> str:
    """Build the status digest against the castle. Heavy imports stay local —
    the stop/session-end hook paths must not pay for them."""
    from swampcastle.castle import Castle
    from swampcastle.services.digest import build_digest
    from swampcastle.settings import CastleSettings
    from swampcastle.storage import factory_from_settings

    settings = CastleSettings()
    with Castle(settings, factory_from_settings(settings), skip_embedder_check=True) as castle:
        return build_digest(castle, project_dir or None).digest


def _spawn_digest_refresh(cache: Path, project_dir: str):
    """Detach a cache rebuild if the served copy has gone stale — the current
    session already has its digest; the refresh benefits the next one."""
    try:
        import time

        if time.time() - cache.stat().st_mtime < DIGEST_REFRESH_SECONDS:
            return
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        log_path = STATE_DIR / "hook.log"
        command = [
            sys.executable,
            "-m",
            "swampcastle",
            "hook",
            "refresh-digest",
            "--project-dir",
            project_dir,
        ]
        with open(log_path, "a") as log_f:
            # start_new_session: same reaping hazard as _maybe_auto_ingest.
            subprocess.Popen(command, stdout=log_f, stderr=log_f, start_new_session=True)
    except OSError:
        pass


def refresh_digest_cache(project_dir: str) -> str:
    """Rebuild the per-project digest cache; returns the digest text."""
    digest = _build_digest_text(project_dir)
    cache = _digest_cache_path(project_dir)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(digest, encoding="utf-8")
    tmp.replace(cache)
    return digest


def hook_session_start(data: dict, harness: str):
    """Session start hook: inject the status digest as session context.

    Serves the per-project cached digest (instant); a cold cache is built
    synchronously once (~20s against the production castle — within Claude
    Code's hook budget).
    """
    parsed = _parse_harness_input(data, harness)
    session_id = parsed["session_id"]
    project_dir = parsed["cwd"]

    _log(f"SESSION START for session {session_id}")

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    cache = _digest_cache_path(project_dir)
    if cache.is_file():
        digest = cache.read_text(encoding="utf-8")
        _spawn_digest_refresh(cache, project_dir)
    else:
        _log(f"digest cache miss for {cache.name}; building synchronously")
        digest = refresh_digest_cache(project_dir)

    _output(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": digest,
            }
        }
    )


def hook_precompact(data: dict, harness: str):
    """Precompact hook: fire-and-forget thin ingest, then let compaction proceed.

    Never blocks — in Claude Code a blocking PreCompact hook prevents
    compaction outright (there is no save-then-retry cycle), holding the
    session hostage. The ingest is backgrounded, not synchronous: the
    transcript file on disk survives compaction, so nothing is lost, and a
    synchronous mine makes /compact wait on embedding (and raised
    TimeoutExpired into the client when mining outran its 60s budget).
    The save-nudge instruction belongs to the protocol adherence milestone,
    not the ingest path.
    """
    parsed = _parse_harness_input(data, harness)
    session_id = parsed["session_id"]
    transcript_path = parsed["transcript_path"]

    _log(f"PRE-COMPACT triggered for session {session_id}")

    _maybe_auto_ingest(transcript_path)

    _output({})


def hook_session_end(data: dict, harness: str):
    """Session end hook: fire-and-forget thin ingest of the final transcript.

    Never blocks — the harness is shutting down; output {} immediately and
    let the backgrounded mine catch the tail exchanges (upstream #1814).
    """
    parsed = _parse_harness_input(data, harness)
    session_id = parsed["session_id"]
    transcript_path = parsed["transcript_path"]

    _log(f"SESSION END for session {session_id} ({harness})")

    _maybe_auto_ingest(transcript_path)

    _output({})


def run_hook(hook_name: str, harness: str):
    """Main entry point: read stdin JSON, dispatch to hook handler."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        _log("WARNING: Failed to parse stdin JSON, proceeding with empty data")
        data = {}

    hooks = {
        "session-start": hook_session_start,
        "stop": hook_stop,
        "precompact": hook_precompact,
        "session-end": hook_session_end,
    }

    handler = hooks.get(hook_name)
    if handler is None:
        print(f"Unknown hook: {hook_name}", file=sys.stderr)
        sys.exit(1)

    try:
        handler(data, harness)
    except Exception:
        # A hook must never surface a traceback into the client. Log the
        # failure and pass through so the harness proceeds.
        _log(f"ERROR: hook {hook_name} crashed:\n{traceback.format_exc()}")
        _output({})
