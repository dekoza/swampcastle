# MCP Integration — Claude Code

## Setup

Run the MCP server:

```bash
python -m swampcastle.drawbridge
```

Or add it to Claude Code:

```bash
claude mcp add swampcastle -- python -m swampcastle.drawbridge
```

## Available Tools

The server exposes the full SwampCastle MCP toolset. Common entry points include:

- **swampcastle_status** — palace stats (wings, rooms, drawer counts)
- **swampcastle_search** — semantic search across all memories
- **swampcastle_list_wings** — list all projects in the palace

## Usage in Claude Code

Once configured, Claude Code can search your memories directly during conversations.
