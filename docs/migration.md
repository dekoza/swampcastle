# Migrating from MemPalace

SwampCastle v4 is a full rewrite of MemPalace v3. Data is compatible — your palace files work — but package names, CLI commands, config paths, and MCP tool names have all changed.

## Quick migration

```bash
# 1. Uninstall mempalace, install swampcastle
pip uninstall mempalace
pip install swampcastle

# 2. Copy your data
cp -r ~/.mempalace ~/.swampcastle

# 3. Update your MCP client
claude mcp remove mempalace
claude mcp add swampcastle -- swampcastle-mcp
```

That's it for basic usage. Details below for specific configurations.

## Data directory

| MemPalace | SwampCastle |
|-----------|-------------|
| `~/.mempalace/` | `~/.swampcastle/` |
| `~/.mempalace/palace/` | `~/.swampcastle/castle/` |
| `~/.mempalace/knowledge_graph.sqlite3` | `~/.swampcastle/knowledge_graph.sqlite3` |
| `~/.mempalace/identity.txt` | `~/.swampcastle/identity.txt` |
| `~/.mempalace/wal/` | `~/.swampcastle/wal/` |
| `~/.mempalace/node_id` | `~/.swampcastle/node_id` |
| `~/.mempalace/config.json` | `~/.swampcastle/config.json` |

Copy the entire directory. The LanceDB palace files and SQLite knowledge graph are binary-compatible.

### Config file changes

In `~/.swampcastle/config.json`, update `palace_path` if it references the old directory:

```json
{
  "palace_path": "/home/user/.swampcastle/castle"
}
```

## Environment variables

| MemPalace | SwampCastle |
|-----------|-------------|
| `MEMPALACE_PALACE_PATH` | `SWAMPCASTLE_CASTLE_PATH` |
| `MEMPALACE_BACKEND` | `SWAMPCASTLE_BACKEND` |
| `MEMPALACE_ONNX_CACHE` | `SWAMPCASTLE_ONNX_CACHE` |
| `MEMPALACE_SOURCE_DIR` | `SWAMPCASTLE_SOURCE_DIR` |

## CLI commands

| MemPalace | SwampCastle | Alias |
|-----------|-------------|-------|
| `mempalace init <dir>` | `swampcastle init <dir>` | — |
| `mempalace mine <dir>` | `swampcastle mine <dir>` | — |
| `mempalace search "query"` | `swampcastle seek "query"` | `search` |
| `mempalace status` | `swampcastle survey` | `status` |
| `mempalace mcp` | `swampcastle drawbridge` | `mcp` |
| `python -m mempalace.mcp_server` | `swampcastle-mcp` | `swampcastle drawbridge run` |
| `mempalace serve` | `swampcastle serve` | — |
| `mempalace sync` | `swampcastle sync` | — |

Old aliases (`search`, `status`, `mcp`) still work for convenience.

## MCP setup

### Claude Code

```bash
# Remove old
claude mcp remove mempalace

# Add new
claude mcp add swampcastle -- swampcastle-mcp
```

### Gemini CLI

```bash
gemini mcp remove mempalace
gemini mcp add swampcastle swampcastle-mcp --scope user
```

## MCP tool names

All 19 tools renamed from `mempalace_*` to `swampcastle_*`:

| MemPalace | SwampCastle |
|-----------|-------------|
| `mempalace_status` | `swampcastle_status` |
| `mempalace_search` | `swampcastle_search` |
| `mempalace_add_drawer` | `swampcastle_add_drawer` |
| `mempalace_delete_drawer` | `swampcastle_delete_drawer` |
| `mempalace_kg_query` | `swampcastle_kg_query` |
| `mempalace_kg_add` | `swampcastle_kg_add` |
| `mempalace_kg_invalidate` | `swampcastle_kg_invalidate` |
| `mempalace_kg_timeline` | `swampcastle_kg_timeline` |
| `mempalace_kg_stats` | `swampcastle_kg_stats` |
| `mempalace_list_wings` | `swampcastle_list_wings` |
| `mempalace_list_rooms` | `swampcastle_list_rooms` |
| `mempalace_get_taxonomy` | `swampcastle_get_taxonomy` |
| `mempalace_check_duplicate` | `swampcastle_check_duplicate` |
| `mempalace_get_aaak_spec` | `swampcastle_get_aaak_spec` |
| `mempalace_traverse` | `swampcastle_traverse` |
| `mempalace_find_tunnels` | `swampcastle_find_tunnels` |
| `mempalace_graph_stats` | `swampcastle_graph_stats` |
| `mempalace_diary_write` | `swampcastle_diary_write` |
| `mempalace_diary_read` | `swampcastle_diary_read` |

## Python imports

| MemPalace | SwampCastle |
|-----------|-------------|
| `from mempalace.searcher import search_memories` | `from swampcastle.services.search import SearchService` |
| `from mempalace.knowledge_graph import KnowledgeGraph` | `from swampcastle.storage.sqlite_graph import SQLiteGraph` |
| `from mempalace.config import MempalaceConfig` | `from swampcastle.settings import CastleSettings` |
| `from mempalace.palace import get_collection` | `from swampcastle.storage.lance import LocalStorageFactory` |
| `from mempalace.layers import MemoryStack` | `from swampcastle.castle import Castle` |
| `from mempalace.mcp_server import handle_request` | `from swampcastle.mcp.server import create_handler` |

The v4 API uses the `Castle` context object instead of calling modules directly:

```python
from swampcastle.castle import Castle
from swampcastle.settings import CastleSettings
from swampcastle.storage.lance import LocalStorageFactory

settings = CastleSettings(castle_path="~/.swampcastle/castle")
factory = LocalStorageFactory(settings.castle_path)

with Castle(settings, factory) as castle:
    result = castle.search.search(SearchQuery(query="auth decisions"))
    castle.vault.add_drawer(AddDrawerCommand(wing="proj", room="auth", content="..."))
    castle.graph.kg_add(subject="Kai", predicate="works_on", obj="Orion")
```

## Hooks

Update hook scripts to reference `swampcastle` instead of `mempalace`:

```bash
# In mempal_save_hook.sh / mempal_precompact_hook.sh
# Change:
python3 -m mempalace mine "$MEMPAL_DIR"
# To:
python3 -m swampcastle mine "$MEMPAL_DIR"
```

## LanceDB collection name

MemPalace used `mempalace_drawers`. SwampCastle uses `swampcastle_chests`. Your existing LanceDB data will work — the collection name is just a table name within the database. If you need to access old data:

```python
factory = LocalStorageFactory(castle_path)
old_col = factory._backend.get_collection(castle_path, "mempalace_drawers", create=False)
```

Or rename the table directory inside your castle path from `mempalace_drawers.lance/` to `swampcastle_chests.lance/`.
