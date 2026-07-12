"""MCP JSON-RPC server — stdin/stdout protocol handler."""

import json
import logging
import sys
from typing import Any

from pydantic import BaseModel, ValidationError

from swampcastle.audit.adherence import AdherenceRecorder
from swampcastle.castle import Castle
from swampcastle.errors import CastleError
from swampcastle.mcp.protocol import SERVER_INSTRUCTIONS
from swampcastle.mcp.tools import ToolDef, register_tools, resolve_tool_name
from swampcastle.version import __version__

logger = logging.getLogger("swampcastle.mcp")

SUPPORTED_PROTOCOL_VERSIONS = ["2025-03-26", "2024-11-05"]

# Modules the write path resolves lazily. pipx reinstall deletes and
# recreates the venv under a live server; imports already resolved keep
# working (deleted-inode mappings), but a lazy import after the swap reads
# the mismatched new tree and throws (observed 2026-07-12, issue #29).
# Everything here gets imported at startup so a deploy can't break a
# running server mid-flight.
WRITE_PATH_MODULES = (
    "concurrent.futures",  # vault distill parallel path
    "lancedb",  # storage open (usually resolved at startup already)
    "numpy",  # embedder encode
    "onnxruntime",  # default embedder backend
    "pyarrow",  # lance upsert / dimension check
    "tokenizers",  # default embedder tokenizer
    "yaml",  # digest project-config resolution
    "swampcastle.dialect",  # vault distill
    "swampcastle.embeddings",  # embedder factory
    "swampcastle.sync_meta",  # lance sync-meta injection
)


def preload_write_path(castle=None, extra_modules: list[str] | None = None) -> list[str]:
    """Resolve every write-path import now; optionally warm the embedder.

    Returns a list of failure descriptions (empty on full success) — a
    partially broken preload must never take the server down, only narrow
    the protection.
    """
    import importlib

    failures: list[str] = []
    for module_name in (*WRITE_PATH_MODULES, *(extra_modules or [])):
        try:
            importlib.import_module(module_name)
        except Exception as e:
            failures.append(f"{module_name}: {e}")

    embedder = getattr(getattr(castle, "_collection", None), "_embedder", None)
    if embedder is not None:
        try:
            embedder.embed(["warmup"])
        except Exception as e:
            failures.append(f"embedder warmup: {e}")

    for failure in failures:
        logger.warning("write-path preload failed: %s", failure)
    return failures


def _logging_handlers(log_dir=None) -> list:
    """Stderr plus a file the client can't drop.

    Claude Code discards MCP server stderr, so a tool traceback logged only
    there is lost — every -32603 the client shows is then undiagnosable
    (observed 2026-07-12). The file handler keeps the evidence.
    """
    from pathlib import Path

    handlers: list = [logging.StreamHandler(sys.stderr)]
    if log_dir is None:
        log_dir = Path.home() / ".swampcastle" / "hook_state"
    try:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "mcp-server.log")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(process)d] %(levelname)s %(name)s: %(message)s")
        )
        handlers.append(file_handler)
    except OSError:
        pass  # a read-only home must not stop the server
    return handlers


def create_handler(castle: Castle, recorder: AdherenceRecorder | None = None):
    """Create a JSON-RPC request handler bound to a Castle instance.

    The adherence recorder rides on the returned handler as `.recorder`
    (instead of a parameter in main()'s call) so tests that monkeypatch
    create_handler with a single-argument lambda keep working.
    """
    tools = register_tools(castle)
    initialized = False
    if recorder is None:
        recorder = AdherenceRecorder.for_castle(str(castle.settings.castle_path))

    def handle(request: dict) -> dict | None:
        nonlocal initialized
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            initialized = True
            recorder.session_started((params or {}).get("clientInfo"))
            client_version = (params or {}).get("protocolVersion", SUPPORTED_PROTOCOL_VERSIONS[-1])
            if client_version in SUPPORTED_PROTOCOL_VERSIONS:
                version = client_version
            else:
                version = SUPPORTED_PROTOCOL_VERSIONS[0]
            return _result(
                req_id,
                {
                    "protocolVersion": version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "swampcastle", "version": __version__},
                    "instructions": SERVER_INSTRUCTIONS,
                },
            )

        if method == "notifications/initialized":
            return None

        if method == "ping":
            return _result(req_id, {})

        if method == "tools/list":
            tool_list = []
            for name, tool in tools.items():
                tool_list.append(
                    {
                        "name": name,
                        "description": tool.description,
                        "inputSchema": tool.input_schema,
                    }
                )
            return _result(req_id, {"tools": tool_list})

        if method == "tools/call":
            tool_name = resolve_tool_name((params or {}).get("name", ""))
            arguments = (params or {}).get("arguments") or {}
            recorder.record_call(tool_name, arguments)
            return _call_tool(req_id, tools, tool_name, arguments)

        return _error(req_id, -32601, f"Unknown method: {method}")

    handle.recorder = recorder
    return handle


def _call_tool(req_id, tools: dict[str, ToolDef], name: str, args: dict) -> dict:
    tool = tools.get(name)
    if not tool:
        return _error(req_id, -32602, f"Unknown tool: {name}")

    try:
        if tool.input_model and args:
            validated = tool.input_model(**args)
            result = tool.handler(validated)
        elif args and not tool.input_model:
            result = tool.handler(**args)
        else:
            result = tool.handler()

        if isinstance(result, BaseModel):
            text = result.model_dump_json()
        elif isinstance(result, str):
            text = result
        else:
            text = json.dumps(result, default=str)

        return _result(
            req_id,
            {
                "content": [{"type": "text", "text": text}],
            },
        )

    except ValidationError as e:
        # Bad arguments, not a server fault: return readable isError content
        # so the calling model can fix its arguments and retry (#31).
        problems = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc']) or 'arguments'}: {err['msg']}"
            for err in e.errors()
        )
        error_body = json.dumps(
            {"error": f"Invalid arguments for {name} — {problems}", "code": "invalid_arguments"}
        )
        return _result(
            req_id,
            {
                "content": [{"type": "text", "text": error_body}],
                "isError": True,
            },
        )
    except CastleError as e:
        error_body = json.dumps({"error": str(e), "code": e.code})
        return _result(
            req_id,
            {
                "content": [{"type": "text", "text": error_body}],
                "isError": True,
            },
        )
    except Exception:
        logger.exception("Tool error in %s", name)
        return _error(req_id, -32603, f"Internal error in tool {name}")


def _result(req_id, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def main():
    """Run MCP server on stdin/stdout."""
    from swampcastle.settings import CastleSettings
    from swampcastle.storage import factory_from_settings

    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=_logging_handlers())

    settings = CastleSettings(_env_file=None)
    factory = factory_from_settings(settings)

    with Castle(settings, factory) as castle:
        handler = create_handler(castle)
        # Resolve write-path imports off the startup path: a venv-swap
        # deploy (#29) can't break what's already imported, and a slow
        # ONNX load must not delay `initialize`.
        import threading

        threading.Thread(
            target=preload_write_path, args=(castle,), name="preload", daemon=True
        ).start()
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                continue
            response = handler(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        # stdin EOF = client disconnected; stamp the session record.
        # (getattr: tests monkeypatch create_handler with bare lambdas.)
        recorder = getattr(handler, "recorder", None)
        if recorder is not None:
            recorder.session_ended()
