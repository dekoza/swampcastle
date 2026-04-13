# Migrating from MemPalace

SwampCastle v4 is a rebuild, not a cosmetic rename.

The major changes are:
- package name: `mempalace` → `swampcastle`
- CLI naming: castle-themed verbs with compatibility aliases
- architecture: module-level helpers → `Castle` + services + storage factories
- default backend: local LanceDB + SQLite
- optional server backend: PostgreSQL + pgvector

## Package and command rename

Install the new package:

```bash
pip uninstall mempalace
pip install swampcastle
```

Common command mapping:

| MemPalace | SwampCastle |
|---|---|
| `mempalace init <dir>` | `swampcastle build <dir>` or `swampcastle init <dir>` |
| `mempalace mine <dir>` | `swampcastle gather <dir>` or `swampcastle mine <dir>` |
| `mempalace search ...` | `swampcastle seek ...` or `swampcastle search ...` |
| `mempalace status` | `swampcastle survey` or `swampcastle status` |
| `mempalace mcp` | `swampcastle drawbridge` or `swampcastle mcp` |
| `python -m mempalace.mcp_server` | `swampcastle-mcp` or `swampcastle drawbridge run` |
| `mempalace serve` | `swampcastle serve` |
| `mempalace sync` | `swampcastle sync` |

## MCP tool rename

All public tool names moved from `mempalace_*` to `swampcastle_*`.

Examples:
- `mempalace_search` → `swampcastle_search`
- `mempalace_status` → `swampcastle_status`
- `mempalace_kg_query` → `swampcastle_kg_query`
- `mempalace_diary_write` → `swampcastle_diary_write`

## Python API migration

Old style:

```python
# old MemPalace-era style
from mempalace.searcher import search_memories
```

v4 style:

```python
from swampcastle.castle import Castle
from swampcastle.models import SearchQuery
from swampcastle.settings import CastleSettings
from swampcastle.storage import factory_from_settings

settings = CastleSettings(_env_file=None)
factory = factory_from_settings(settings)

with Castle(settings, factory) as castle:
    result = castle.search.search(SearchQuery(query="auth decisions"))
```

## Storage migration reality check

This part is still in flux and the docs will not lie about it.

- `swampcastle raise` / `swampcastle migrate` is the new CLI entry point name
- the current CLI command only prints guidance
- the legacy standalone `swampcastle.migrate` module still contains older Chroma-oriented recovery logic and is being replaced

So if you are migrating old Chroma-backed data, treat the migration path as **in progress**, not as a polished one-command v4 workflow.

## Path rename

The v4 defaults use `~/.swampcastle/` and `~/.swampcastle/castle`.

If you are carrying forward local artifacts from an older setup, the most important paths to audit are:
- castle / palace directory
- WAL directory
- sync metadata files
- MCP client configuration

## Client reconfiguration

Claude Code:

```bash
claude mcp remove mempalace
claude mcp add swampcastle -- swampcastle-mcp
```

Gemini CLI:

```bash
gemini mcp remove mempalace
gemini mcp add swampcastle swampcastle-mcp --scope user
```

## Practical advice

Migrate in this order:

1. install `swampcastle`
2. reconfigure your MCP client
3. switch your Python imports to `Castle` + services + factories
4. validate ingest / search on fresh data
5. then handle old Chroma-era storage conversion deliberately
