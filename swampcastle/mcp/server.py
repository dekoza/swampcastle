"""MCP JSON-RPC server — stdin/stdout protocol handler."""

import json
import logging
import sys
from typing import Any

from pydantic import BaseModel

from swampcastle.castle import Castle
from swampcastle.errors import CastleError
from swampcastle.mcp.tools import ToolDef, register_tools
from swampcastle.version import __version__

logger = logging.getLogger("swampcastle.mcp")

SUPPORTED_PROTOCOL_VERSIONS = ["2025-03-26", "2024-11-05"]


def create_handler(castle: Castle):
    """Create a JSON-RPC request handler bound to a Castle instance."""
    tools = register_tools(castle)
    initialized = False

    def handle(request: dict) -> dict | None:
        nonlocal initialized
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            initialized = True
            client_version = (params or {}).get("protocolVersion", SUPPORTED_PROTOCOL_VERSIONS[-1])
            if client_version in SUPPORTED_PROTOCOL_VERSIONS:
                version = client_version
            else:
                version = SUPPORTED_PROTOCOL_VERSIONS[0]
            return _result(req_id, {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "swampcastle", "version": __version__},
            })

        if method == "notifications/initialized":
            return None

        if method == "ping":
            return _result(req_id, {})

        if method == "tools/list":
            tool_list = []
            for name, tool in tools.items():
                tool_list.append({
                    "name": name,
                    "description": tool.description,
                    "inputSchema": tool.input_schema,
                })
            return _result(req_id, {"tools": tool_list})

        if method == "tools/call":
            tool_name = (params or {}).get("name", "")
            arguments = (params or {}).get("arguments") or {}
            return _call_tool(req_id, tools, tool_name, arguments)

        return _error(req_id, -32601, f"Unknown method: {method}")

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

        return _result(req_id, {
            "content": [{"type": "text", "text": text}],
        })

    except CastleError as e:
        error_body = json.dumps({"error": str(e), "code": e.code})
        return _result(req_id, {
            "content": [{"type": "text", "text": error_body}],
            "isError": True,
        })
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

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    settings = CastleSettings(_env_file=None)
    factory = factory_from_settings(settings)

    with Castle(settings, factory) as castle:
        handler = create_handler(castle)
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
