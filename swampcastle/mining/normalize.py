#!/usr/bin/env python3
"""
normalize.py — Convert any chat export format to MemPalace transcript format.

Supported:
    - Plain text with > markers (pass through)
    - Claude.ai JSON export
    - ChatGPT conversations.json
    - Claude Code JSONL
    - OpenAI Codex CLI JSONL
    - Pi agent JSONL
    - Slack JSON export
    - Plain text (pass through for paragraph chunking)

No API key. No internet. Everything local.
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

# =============================================================================
# NOISE STRIPPING (upstream #785)
#
# Harness-injected chrome must not become memories: system tags, hook output,
# and Claude Code TUI markers are removed per message, never across message
# boundaries. Every pattern is line-anchored and the tag body refuses to cross
# blank lines, so a stray unclosed tag in one message can never eat content
# from neighboring messages. When in doubt, leave text alone.
# =============================================================================

_NOISE_TAGS = (
    "system-reminder",
    "command-message",
    "command-name",
    "task-notification",
    "user-prompt-submit-hook",
    "hook_output",
    "local-command-caveat",
    "local-command-stdout",
)


def _tag_pattern(name: str) -> "re.Pattern[str]":
    # Opening tag must begin a line (optionally after a `> ` blockquote marker,
    # since _messages_to_transcript prefixes user turns with `> `). Body is lazy
    # but forbidden from crossing a blank line, so a dangling open tag can't
    # span multiple messages. Closing tag eats optional trailing whitespace.
    return re.compile(
        rf"(?m)^(?:> )?<{name}(?:\s[^>]*)?>" rf"(?:(?!\n\s*\n)[\s\S])*?" rf"</{name}>[ \t]*\n?"
    )


_NOISE_TAG_PATTERNS = [_tag_pattern(t) for t in _NOISE_TAGS]

# Strings that identify an entire noise line when found at its start.
# Matched case-sensitively and anchored to line-start so user prose mentioning
# e.g. "current time:" in a sentence is untouched. The MemPalace-era prefixes
# stay: this machine's transcript history predates the fork.
_NOISE_LINE_PREFIXES = (
    "CURRENT TIME:",
    "VERIFIED FACTS (do not contradict)",
    "AGENT SPECIALIZATION:",
    "Checking verified facts...",
    "Injecting timestamp...",
    "Starting background pipeline...",
    "Checking emotional weights...",
    "Auto-save reminder...",
    "Checking pipeline...",
    "MemPalace auto-save checkpoint.",
)

_NOISE_LINE_PATTERNS = [
    re.compile(rf"(?m)^(?:> )?{re.escape(p)}.*\n?") for p in _NOISE_LINE_PREFIXES
]

# Claude Code TUI hook-run chrome, e.g. "Ran 2 Stop hooks". Line-anchored,
# case-sensitive, explicit hook names — prose like "our CI has a stop hook"
# stays intact.
_HOOK_LINE_RE = re.compile(
    r"(?m)^(?:> )?Ran \d+ (?:Stop|PreCompact|PreToolUse|PostToolUse|UserPromptSubmit|Notification|SessionStart|SessionEnd) hook[s]?.*\n?"
)

# "… +N lines" collapsed-output marker, line-anchored.
_COLLAPSED_LINES_RE = re.compile(r"(?m)^(?:> )?…\s*\+\d+ lines.*\n?")

# Claude Code collapsed-output chrome "[N tokens] (ctrl+o to expand)".
# Narrow shape — a bare "(ctrl+o to expand)" in user prose stays intact.
_TOKEN_CHROME_RE = re.compile(r"\s*\[\d+\s+tokens?\]\s*\(ctrl\+o to expand\)")


def strip_noise(text: str) -> str:
    """Remove system tags, hook output, and harness UI chrome from text.

    All patterns are line-anchored. User prose that happens to mention these
    strings inline (e.g., documenting them) is preserved verbatim.
    """
    for pat in _NOISE_TAG_PATTERNS:
        text = pat.sub("", text)
    for pat in _NOISE_LINE_PATTERNS:
        text = pat.sub("", text)
    text = _HOOK_LINE_RE.sub("", text)
    text = _COLLAPSED_LINES_RE.sub("", text)
    text = _TOKEN_CHROME_RE.sub("", text)
    # Collapse runs of blank lines created by the removals
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def normalize(filepath: str) -> str:
    """
    Load a file and normalize to transcript format if it's a chat export.
    Plain text files pass through unchanged.
    """
    try:
        file_size = os.path.getsize(filepath)
    except OSError as e:
        raise IOError(f"Could not read {filepath}: {e}")
    if file_size > 500 * 1024 * 1024:  # 500 MB safety limit
        raise IOError(f"File too large ({file_size // (1024 * 1024)} MB): {filepath}")
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        raise IOError(f"Could not read {filepath}: {e}")

    if not content.strip():
        return content

    # Already has > markers — pass through
    lines = content.split("\n")
    if sum(1 for line in lines if line.strip().startswith(">")) >= 3:
        return content

    # Try JSON normalization
    ext = Path(filepath).suffix.lower()
    if ext in (".json", ".jsonl") or content.strip()[:1] in ("{", "["):
        normalized = _try_normalize_json(content)
        if normalized:
            return normalized

    return content


def _try_normalize_json(content: str) -> Optional[str]:
    """Try all known JSON chat schemas."""

    normalized = _try_claude_code_jsonl(content)
    if normalized:
        return normalized

    normalized = _try_codex_jsonl(content)
    if normalized:
        return normalized

    normalized = _try_pi_jsonl(content)
    if normalized:
        return normalized

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None

    for parser in (_try_claude_ai_json, _try_chatgpt_json, _try_slack_json):
        normalized = parser(data)
        if normalized:
            return normalized

    return None


def _try_claude_code_jsonl(content: str) -> Optional[str]:
    """Claude Code JSONL sessions."""
    lines = [line.strip() for line in content.strip().split("\n") if line.strip()]
    messages = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        msg_type = entry.get("type", "")
        message = entry.get("message", {})
        if msg_type in ("human", "user"):
            text = _extract_content(message.get("content", ""))
            # Strip harness-injected noise per message, never across message
            # boundaries — prevents span-eating (#785).
            if text:
                text = strip_noise(text)
            if text:
                messages.append(("user", text))
        elif msg_type == "assistant":
            text = _extract_content(message.get("content", ""))
            if text:
                text = strip_noise(text)
            if text:
                messages.append(("assistant", text))
    if len(messages) >= 2:
        return _messages_to_transcript(messages)
    return None


def _try_codex_jsonl(content: str) -> Optional[str]:
    """OpenAI Codex CLI sessions (~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl).

    Uses only event_msg entries (user_message / agent_message) which represent
    the canonical conversation turns. response_item entries are skipped because
    they include synthetic context injections and duplicate the real messages.
    """
    lines = [line.strip() for line in content.strip().split("\n") if line.strip()]
    messages = []
    has_session_meta = False
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue

        entry_type = entry.get("type", "")
        if entry_type == "session_meta":
            has_session_meta = True
            continue

        if entry_type != "event_msg":
            continue

        payload = entry.get("payload", {})
        if not isinstance(payload, dict):
            continue

        payload_type = payload.get("type", "")
        msg = payload.get("message")
        if not isinstance(msg, str):
            continue
        text = msg.strip()
        if not text:
            continue

        if payload_type == "user_message":
            messages.append(("user", text))
        elif payload_type == "agent_message":
            messages.append(("assistant", text))

    if len(messages) >= 2 and has_session_meta:
        return _messages_to_transcript(messages)
    return None


def _try_pi_jsonl(content: str) -> Optional[str]:
    """Pi agent sessions (~/.pi/agent/sessions/{escaped-cwd}/{timestamp}_{uuid}.jsonl).

    Pi stores sessions as JSONL with a tree-structured message history.
    Only {"type": "message"} entries are conversation; event entries
    (model_change, thinking_level_change, custom_message, compaction, ...)
    are operational and skipped, as are messages with role "toolResult".
    Content is a string or a block list; _extract_content keeps only
    "text" blocks, so thinking/toolCall/image blocks drop out.

    Gated on the {"type": "session", "version": ...} header line so other
    JSONL dialects never match. The parentId tree is read linearly, so
    abandoned branches interleave — accepted, matching upstream MemPalace.
    """
    lines = [line.strip() for line in content.strip().split("\n") if line.strip()]
    messages = []
    has_session_header = False
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue

        entry_type = entry.get("type", "")
        if entry_type == "session" and "version" in entry:
            has_session_header = True
            continue

        if entry_type != "message":
            continue

        message = entry.get("message", {})
        if not isinstance(message, dict):
            continue

        role = message.get("role", "")
        text = _extract_content(message.get("content", ""))
        # Pi transcripts carry the same harness-injected tags (verified on
        # real sessions) — strip per message here too (#785).
        if text:
            text = strip_noise(text)

        if role == "user" and text:
            messages.append(("user", text))
        elif role == "assistant" and text:
            messages.append(("assistant", text))

    if len(messages) >= 2 and has_session_header:
        return _messages_to_transcript(messages)
    return None


def _try_claude_ai_json(data) -> Optional[str]:
    """Claude.ai JSON export: flat messages list or privacy export with chat_messages."""
    if isinstance(data, dict):
        data = data.get("messages", data.get("chat_messages", []))
    if not isinstance(data, list):
        return None

    # Privacy export: array of conversation objects with chat_messages inside each
    if data and isinstance(data[0], dict) and "chat_messages" in data[0]:
        all_messages = []
        for convo in data:
            if not isinstance(convo, dict):
                continue
            chat_msgs = convo.get("chat_messages", [])
            for item in chat_msgs:
                if not isinstance(item, dict):
                    continue
                role = item.get("role", "")
                text = _extract_content(item.get("content", ""))
                if role in ("user", "human") and text:
                    all_messages.append(("user", text))
                elif role in ("assistant", "ai") and text:
                    all_messages.append(("assistant", text))
        if len(all_messages) >= 2:
            return _messages_to_transcript(all_messages)
        return None

    # Flat messages list
    messages = []
    for item in data:
        if not isinstance(item, dict):
            continue
        role = item.get("role", "")
        text = _extract_content(item.get("content", ""))
        if role in ("user", "human") and text:
            messages.append(("user", text))
        elif role in ("assistant", "ai") and text:
            messages.append(("assistant", text))
    if len(messages) >= 2:
        return _messages_to_transcript(messages)
    return None


def _try_chatgpt_json(data) -> Optional[str]:
    """ChatGPT conversations.json with mapping tree."""
    if not isinstance(data, dict) or "mapping" not in data:
        return None
    mapping = data["mapping"]
    messages = []
    # Find root: prefer node with parent=None AND no message (synthetic root)
    root_id = None
    fallback_root = None
    for node_id, node in mapping.items():
        if node.get("parent") is None:
            if node.get("message") is None:
                root_id = node_id
                break
            elif fallback_root is None:
                fallback_root = node_id
    if not root_id:
        root_id = fallback_root
    if root_id:
        current_id = root_id
        visited = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            node = mapping.get(current_id, {})
            msg = node.get("message")
            if msg:
                role = msg.get("author", {}).get("role", "")
                content = msg.get("content", {})
                parts = content.get("parts", []) if isinstance(content, dict) else []
                text = " ".join(str(p) for p in parts if isinstance(p, str) and p).strip()
                if role == "user" and text:
                    messages.append(("user", text))
                elif role == "assistant" and text:
                    messages.append(("assistant", text))
            children = node.get("children", [])
            current_id = children[0] if children else None
    if len(messages) >= 2:
        return _messages_to_transcript(messages)
    return None


def _try_slack_json(data) -> Optional[str]:
    """
    Slack channel export: [{"type": "message", "user": "...", "text": "..."}]
    Optimized for 2-person DMs. In channels with 3+ people, alternating
    speakers are labeled user/assistant to preserve the exchange structure.
    """
    if not isinstance(data, list):
        return None
    messages = []
    seen_users = {}
    last_role = None
    for item in data:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        user_id = item.get("user", item.get("username", ""))
        text = item.get("text", "").strip()
        if not text or not user_id:
            continue
        if user_id not in seen_users:
            # Alternate roles so exchange chunking works with any number of speakers
            if not seen_users:
                seen_users[user_id] = "user"
            elif last_role == "user":
                seen_users[user_id] = "assistant"
            else:
                seen_users[user_id] = "user"
        last_role = seen_users[user_id]
        messages.append((seen_users[user_id], text))
    if len(messages) >= 2:
        return _messages_to_transcript(messages)
    return None


def _extract_content(content) -> str:
    """Pull text from content — handles str, list of blocks, or dict."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return " ".join(parts).strip()
    if isinstance(content, dict):
        return content.get("text", "").strip()
    return ""


def _messages_to_transcript(messages: list, spellcheck: bool = True) -> str:
    """Convert [(role, text), ...] to transcript format with > markers."""
    if spellcheck:
        try:
            from swampcastle.spellcheck import spellcheck_user_text

            _fix = spellcheck_user_text
        except ImportError:
            _fix = None
    else:
        _fix = None

    lines = []
    i = 0
    while i < len(messages):
        role, text = messages[i]
        if role == "user":
            if _fix is not None:
                text = _fix(text)
            lines.append(f"> {text}")
            if i + 1 < len(messages) and messages[i + 1][0] == "assistant":
                lines.append(messages[i + 1][1])
                i += 2
            else:
                i += 1
        else:
            lines.append(text)
            i += 1
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python normalize.py <filepath>")
        sys.exit(1)
    filepath = sys.argv[1]
    result = normalize(filepath)
    quote_count = sum(1 for line in result.split("\n") if line.strip().startswith(">"))
    print(f"\nFile: {os.path.basename(filepath)}")
    print(f"Normalized: {len(result)} chars | {quote_count} user turns detected")
    print("\n--- Preview (first 20 lines) ---")
    print("\n".join(result.split("\n")[:20]))
