"""The MCP server must log tool tracebacks somewhere the client can't drop.

Claude Code discards MCP server stderr — a traceback logged only there is
lost, and every -32603 the client reports becomes undiagnosable (observed
2026-07-12 during the czytelnia write-failure incident)."""

import logging

from swampcastle.mcp.server import _logging_handlers


def test_logging_handlers_include_file(tmp_path):
    handlers = _logging_handlers(log_dir=tmp_path)
    file_handlers = [h for h in handlers if isinstance(h, logging.FileHandler)]
    assert file_handlers, "no file handler — tracebacks would vanish with stderr"
    assert (tmp_path / "mcp-server.log").exists() or file_handlers[0].baseFilename.endswith(
        "mcp-server.log"
    )


def test_exception_reaches_the_file(tmp_path):
    handlers = _logging_handlers(log_dir=tmp_path)
    test_logger = logging.getLogger("swampcastle.mcp.test-capture")
    test_logger.handlers = [h for h in handlers if isinstance(h, logging.FileHandler)]
    test_logger.propagate = False
    try:
        raise ValueError("boom-for-the-log")
    except ValueError:
        test_logger.exception("Tool error in %s", "diary_write")
    for h in test_logger.handlers:
        h.flush()
    content = (tmp_path / "mcp-server.log").read_text()
    assert "Tool error in diary_write" in content
    assert "boom-for-the-log" in content
    assert "Traceback" in content


def test_unwritable_log_dir_does_not_break_server():
    handlers = _logging_handlers(log_dir="/nonexistent/deeply/nested")
    assert len(handlers) >= 1  # stderr handler survives
