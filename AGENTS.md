# AGENTS.md

> How to build, test, and contribute to SwampCastle.

## Setup

```bash
pip install -e ".[dev]"
```

## Commands

```bash
# Run unit tests (fast, in-memory — default for TDD)
uv run pytest tests/ -v --ignore=tests/benchmarks -k "not integration"

# Run integration tests (real LanceDB + SQLite)
uv run pytest tests/ -v -m integration

# Run all tests
uv run pytest tests/ -v --ignore=tests/benchmarks

# Lint
ruff check .

# Format
ruff format .
```

## Architecture

```
Castle (context object)
  ├── settings: CastleSettings (Pydantic BaseSettings)
  ├── collection: CollectionStore (ABC)
  ├── graph: GraphStore (ABC)
  ├── catalog: CatalogService — status, wings, rooms, taxonomy
  ├── search: SearchService — semantic search, duplicate check
  ├── vault: VaultService — add/delete drawers, diary
  └── graph: GraphService — KG ops, traversal, tunnels

Storage:
  StorageFactory (ABC)
    ├── InMemoryStorageFactory — unit tests
    ├── LocalStorageFactory — LanceDB + SQLite (production)
    └── PostgresStorageFactory — pgvector + SQL (planned)

MCP: mcp/tools.py registers 19 tools, schemas from Pydantic models
CLI: cli/main.py thin dispatcher over Castle services
```

## Project structure

```
swampcastle/
├── castle.py              # Castle context + AsyncCastle wrapper
├── settings.py            # CastleSettings (Pydantic BaseSettings)
├── errors.py              # CastleError hierarchy
├── wal.py                 # WalWriter audit log
├── query_sanitizer.py     # Search query sanitization
├── storage/
│   ├── base.py            # CollectionStore, GraphStore ABCs
│   ├── memory.py          # InMemory backends (testing)
│   ├── lance.py           # LanceDB + LocalStorageFactory
│   └── sqlite_graph.py    # SQLite KG backend
├── services/
│   ├── catalog.py         # CatalogService
│   ├── search.py          # SearchService
│   ├── vault.py           # VaultService
│   └── graph.py           # GraphService
├── models/
│   ├── drawer.py          # Search, drawer I/O models
│   ├── kg.py              # Knowledge graph models
│   ├── catalog.py         # Status/taxonomy models
│   ├── diary.py           # Diary models
│   └── sync.py            # Sync models
├── mcp/
│   ├── server.py          # JSON-RPC handler
│   └── tools.py           # Tool registry (19 tools)
├── cli/
│   └── main.py            # CLI dispatcher
├── mining/
│   ├── miner.py           # Project file ingest
│   ├── convo.py           # Conversation ingest
│   ├── normalize.py       # Format detection
│   └── rooms.py           # Room detection
├── embeddings.py          # Pluggable embedders (ONNX, ST, Ollama)
├── dialect.py             # AAAK compression
├── sync.py                # Sync engine
├── sync_client.py         # HTTP sync client
├── sync_meta.py           # Node identity + sequence counter
├── sync_server.py         # FastAPI sync server
└── version.py             # Version string
```

## Conventions

- **Python style**: snake_case for functions/variables, PascalCase for classes
- **Linter**: ruff with E/F/W rules
- **Formatter**: ruff format, double quotes
- **Commits**: conventional commits (`fix:`, `feat:`, `test:`, `docs:`, `ci:`)
- **Tests**: `tests/test_*.py`, fixtures in `tests/conftest.py`
- **TDD**: write tests first, verify they fail, then implement

## Key files for common tasks

- **Adding an MCP tool**: `swampcastle/mcp/tools.py` — add Pydantic input model + handler in `register_tools()`
- **Adding a service method**: appropriate `swampcastle/services/*.py`, add Pydantic I/O models in `swampcastle/models/`
- **Adding a storage backend**: subclass `CollectionStore`/`GraphStore` in `swampcastle/storage/`, add factory
- **Changing search**: `swampcastle/services/search.py`
- **Modifying mining**: `swampcastle/mining/miner.py` (files) or `swampcastle/mining/convo.py` (conversations)
- **Configuration**: `swampcastle/settings.py` — add field to `CastleSettings`
