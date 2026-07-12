"""Tests for the pi harness, session-end hook, and the install-hooks command."""

import contextlib
import io
import json
from unittest.mock import patch

from swampcastle.hooks_cli import (
    SUPPORTED_HARNESSES,
    _parse_harness_input,
    hook_session_end,
    run_hook,
)
from swampcastle.hooks_install import (
    CLAUDE_HOOK_EVENTS,
    WRAPPER_SCRIPT,
    install_claude_hooks,
    install_pi_extension,
    install_wrapper,
)

# --- pi harness ---


def test_pi_harness_supported():
    assert "pi" in SUPPORTED_HARNESSES


def test_parse_harness_input_pi():
    parsed = _parse_harness_input(
        {"session_id": "abc-123", "transcript_path": "/tmp/s.jsonl"}, "pi"
    )
    assert parsed["session_id"] == "abc-123"
    assert parsed["transcript_path"] == "/tmp/s.jsonl"


# --- hook_session_end ---


def _capture(hook_fn, data, harness):
    buf = io.StringIO()
    with patch("swampcastle.hooks_cli._output", side_effect=lambda d: buf.write(json.dumps(d))):
        hook_fn(data, harness)
    return json.loads(buf.getvalue())


def test_session_end_outputs_empty_and_ingests(tmp_path):
    transcript = tmp_path / "s.jsonl"
    transcript.write_text("{}\n")
    calls = []
    with patch("swampcastle.hooks_cli._maybe_auto_ingest", side_effect=lambda p: calls.append(p)):
        result = _capture(
            hook_session_end,
            {"session_id": "s1", "transcript_path": str(transcript)},
            "claude-code",
        )
    assert result == {}
    assert calls == [str(transcript)]


def test_session_end_pi_harness(tmp_path):
    transcript = tmp_path / "s.jsonl"
    transcript.write_text("{}\n")
    calls = []
    with patch("swampcastle.hooks_cli._maybe_auto_ingest", side_effect=lambda p: calls.append(p)):
        result = _capture(
            hook_session_end,
            {"session_id": "s1", "transcript_path": str(transcript)},
            "pi",
        )
    assert result == {}
    assert calls == [str(transcript)]


def test_run_hook_dispatches_session_end(tmp_path):
    payload = json.dumps({"session_id": "s1", "transcript_path": ""})
    buf = io.StringIO()
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch("sys.stdin", io.StringIO(payload)))
        stack.enter_context(
            patch("swampcastle.hooks_cli._output", side_effect=lambda d: buf.write(json.dumps(d)))
        )
        run_hook("session-end", "pi")
    assert json.loads(buf.getvalue()) == {}


# --- wrapper script ---


def test_wrapper_detaches_passthrough_hooks():
    """session-end/precompact must answer {} instantly and detach the work —
    client shutdown reaps the hook's process group (observed: Claude Code
    "Hook cancelled" killed the SessionEnd mine before it filed anything)."""
    assert "setsid" in WRAPPER_SCRIPT
    assert "disown" in WRAPPER_SCRIPT
    assert "session-end" in WRAPPER_SCRIPT
    assert "precompact" in WRAPPER_SCRIPT
    assert "printf '{}" in WRAPPER_SCRIPT


def test_wrapper_script_ladder():
    assert "SWAMPCASTLE_PYTHON" in WRAPPER_SCRIPT
    assert "command -v swampcastle" in WRAPPER_SCRIPT
    assert "SWAMPCASTLE_INTERNAL=1" in WRAPPER_SCRIPT
    # env-wrapper shebangs must not be accepted as interpreters
    assert "python*" in WRAPPER_SCRIPT


def test_install_wrapper_writes_executable(tmp_path):
    path = install_wrapper(hooks_dir=tmp_path)
    assert path.read_text() == WRAPPER_SCRIPT
    assert path.stat().st_mode & 0o111


# --- claude code settings ---


def test_install_claude_hooks_fresh(tmp_path):
    settings = tmp_path / "settings.json"
    wrapper = tmp_path / "wrapper.sh"
    changed = install_claude_hooks(settings_path=settings, wrapper_path=wrapper)
    assert changed
    data = json.loads(settings.read_text())
    for event in CLAUDE_HOOK_EVENTS:
        entries = data["hooks"][event]
        commands = [h["command"] for e in entries for h in e["hooks"]]
        assert any(str(wrapper) in c for c in commands)


def test_install_claude_hooks_idempotent(tmp_path):
    settings = tmp_path / "settings.json"
    wrapper = tmp_path / "wrapper.sh"
    install_claude_hooks(settings_path=settings, wrapper_path=wrapper)
    first = settings.read_text()
    changed = install_claude_hooks(settings_path=settings, wrapper_path=wrapper)
    assert not changed
    assert settings.read_text() == first


def test_install_claude_hooks_preserves_existing(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "model": "opus",
                "hooks": {
                    "SessionEnd": [{"hooks": [{"type": "command", "command": "other-tool run"}]}]
                },
            }
        )
    )
    wrapper = tmp_path / "wrapper.sh"
    install_claude_hooks(settings_path=settings, wrapper_path=wrapper)
    data = json.loads(settings.read_text())
    assert data["model"] == "opus"
    commands = [h["command"] for e in data["hooks"]["SessionEnd"] for h in e["hooks"]]
    assert "other-tool run" in commands
    assert any(str(wrapper) in c for c in commands)


def test_install_claude_hooks_session_start_matcher(tmp_path):
    """SessionStart re-injects the digest on every context reset — startup,
    resume, clear, and post-compact."""
    settings = tmp_path / "settings.json"
    wrapper = tmp_path / "wrapper.sh"
    install_claude_hooks(settings_path=settings, wrapper_path=wrapper)
    data = json.loads(settings.read_text())
    entries = data["hooks"]["SessionStart"]
    ours = [e for e in entries if any(str(wrapper) in h["command"] for h in e["hooks"])]
    assert len(ours) == 1
    assert ours[0]["matcher"] == "startup|resume|clear|compact"
    assert "--hook session-start" in ours[0]["hooks"][0]["command"]


def test_install_claude_hooks_adds_session_start_to_existing_install(tmp_path):
    """A settings file from a pre-#26 install (SessionEnd/PreCompact already
    wired) still gains the SessionStart entry."""
    settings = tmp_path / "settings.json"
    wrapper = tmp_path / "wrapper.sh"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionEnd": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f"{wrapper} --hook session-end --harness claude-code",
                                }
                            ]
                        }
                    ]
                }
            }
        )
    )
    changed = install_claude_hooks(settings_path=settings, wrapper_path=wrapper)
    assert changed
    data = json.loads(settings.read_text())
    assert "SessionStart" in data["hooks"]
    assert len(data["hooks"]["SessionEnd"]) == 1


# --- pi extension ---


def test_install_pi_extension_writes_ts(tmp_path):
    wrapper = tmp_path / "wrapper.sh"
    path = install_pi_extension(extensions_dir=tmp_path / "ext", wrapper_path=wrapper)
    content = path.read_text()
    assert path.name == "swampcastle-hooks.ts"
    assert "session_shutdown" in content
    assert str(wrapper) in content
    assert "--harness" in content and "pi" in content


def test_install_pi_extension_injects_digest(tmp_path):
    """pi has no additionalContext analogue — the extension fetches the digest
    through the same session-start hook and injects it as a persistent message
    on the first before_agent_start after each session_start."""
    wrapper = tmp_path / "wrapper.sh"
    path = install_pi_extension(extensions_dir=tmp_path / "ext", wrapper_path=wrapper)
    content = path.read_text()
    assert '"session_start"' in content
    assert '"before_agent_start"' in content
    assert "session-start" in content
    assert "additionalContext" in content
    # digest fetch starts at session_start; injection must not repeat per turn
    assert "digestInjected" in content
