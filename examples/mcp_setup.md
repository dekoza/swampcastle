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

- **status** — palace stats (wings, rooms, drawer counts)
- **search** — semantic search across all memories
- **list_wings** — list all projects in the palace

Some MCP clients add the server namespace when rendering tool names, so you may still see
forms like `swampcastle_search` in the UI even though raw discovery now advertises `search`.

## Usage in Claude Code

Once configured, Claude Code can search your memories directly during conversations.
