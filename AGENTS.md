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
  ├── vault: VaultService — add/delete drawers, diary, tombstones, distill, reforge
  ├── graph: GraphService — KG ops, traversal, tunnels
  ├── audit: AuditService — origin manifests, curation, catalog cards
  └── kg_proposals: KGProposalService — candidate triple workflow

Storage:
  StorageFactory (ABC)
    ├── InMemoryStorageFactory — unit tests
    ├── LocalStorageFactory — LanceDB + SQLite (production)
    └── PostgresStorageFactory — pgvector + SQLAlchemy (planned)

MCP: mcp/tools.py registers 27 tools (including typed-record tools), schemas from Pydantic models
CLI: cli/main.py thin dispatcher → cli/commands/ subpackage
```

## Project structure

```
swampcastle/
├── castle.py              # Castle context + AsyncCastle wrapper
├── settings.py            # CastleSettings (Pydantic BaseSettings)
├── errors.py              # CastleError hierarchy
├── wal.py                 # WalWriter audit log
├── query_sanitizer.py     # Search query sanitization
├── embeddings.py          # Pluggable embedders (ONNX, ST, Ollama)
├── dialect.py             # AAAK compression
├── entity_detector.py     # Entity detection
├── entity_registry.py     # Entity registry
├── dedup.py               # Deduplication
├── spellcheck.py          # Spell checking
├── split_mega_files.py    # Split mega-files into sessions
├── migrate.py             # Migration (ChromaDB → LanceDB)
├── onboarding.py          # Onboarding flow
├── wizard.py              # Configuration wizard
├── tuning.py              # ONNX CPU tuning
├── project_config.py      # Project-local mining config
├── runtime_config.py      # Runtime config
├── hooks_cli.py           # Hook CLI handlers
├── instructions_cli.py    # Instructions CLI handlers
├── lancedb_compat.py      # LanceDB compatibility layer
├── parallel_benchmarks.py # Parallel benchmark utilities
├── sync.py                # Sync engine (ChangeSet, MergeResult)
├── sync_client.py         # HTTP sync client
├── sync_meta.py           # Node identity + sequence counter
├── sync_server.py         # FastAPI sync server
├── version.py             # Version string
├── storage/
│   ├── __init__.py        # StorageFactory ABC, detect_backend, factory_from_settings
│   ├── base.py            # CollectionStore, GraphStore ABCs
│   ├── memory.py          # InMemory backends (testing)
│   ├── lance.py           # LanceDB + LocalStorageFactory
│   ├── sqlite_graph.py    # SQLite KG backend
│   └── postgres.py        # Postgres backend (pgvector + SQLAlchemy)
├── services/
│   ├── catalog.py         # CatalogService
│   ├── search.py          # SearchService (+ hybrid retrieval)
│   ├── graph.py           # GraphService
│   ├── audit.py           # AuditService
│   ├── kg_proposals.py    # KGProposalService
│   └── vault/             # Vault service subpackage
│       ├── __init__.py    # Re-exports VaultService, DiaryReadQuery, GCCollectResult
│       ├── service.py     # VaultService (drawers, diary, tombstones)
│       ├── models.py      # DiaryReadQuery, GCCollectResult
│       ├── distill.py     # DistillEngine (AAAK compression)
│       └── reforge.py     # ReforgeEngine (batch re-embedding)
├── models/
│   ├── __init__.py        # Re-exports all Pydantic I/O models
│   ├── drawer.py          # Search, drawer I/O models
│   ├── kg.py              # Knowledge graph models
│   ├── kg_candidates.py   # KG candidate triple models
│   ├── catalog.py         # Status/taxonomy models
│   ├── diary.py           # Diary models
│   ├── sync.py            # Sync models (ChangeSet, MergeResult, etc.)
│   ├── audit.py           # Audit overlay models
│   ├── origin.py          # Source origin models
│   ├── derived.py         # Derived artifact models
│   └── record.py          # Typed record envelope (RecordEnvelope, RecordKind)
├── audit/                 # Audit overlay (file-based, not DB-backed)
│   ├── __init__.py        # Re-exports curation, derived, origin
│   ├── curation.py        # Alias/tunnel/wing-note curation
│   ├── derived.py         # Catalog cards, search traces
│   └── origin.py          # Source origin manifests
├── retrieval/
│   ├── __init__.py        # Hybrid retrieval
│   └── hybrid.py          # Lexical reranking, sparse candidates, merge
├── mining/
│   ├── __init__.py        # Mining package
│   ├── miner.py           # Project file ingest
│   ├── convo.py           # Conversation ingest
│   ├── normalize.py       # Format detection
│   ├── rooms.py           # Room detection
│   ├── contributor.py     # Contributor tracking
│   ├── extractors.py      # KG candidate extraction from text
│   ├── kg_extract.py      # KG extraction orchestration
│   ├── skeleton.py        # Skeleton detection
│   └── adapters/          # Internal source adapters
│       ├── __init__.py    # Re-exports BaseSourceAdapter + concrete adapters
│       ├── base.py        # BaseSourceAdapter ABC, SourceItem types
│       ├── project_files.py  # ProjectFilesAdapter
│       └── conversation_exports.py  # ConversationExportsAdapter
├── mcp/
│   ├── __init__.py
│   ├── server.py          # JSON-RPC handler
│   └── tools.py           # Tool registry (27 tools)
├── cli/
│   ├── __init__.py
│   ├── main.py            # argparse setup + dispatch
│   └── commands/          # CLI command handlers subpackage
│       ├── __init__.py    # Re-exports all command handlers + shared utilities
│       ├── shared.py      # Shared helpers (_print_kv, _print_section, etc.)
│       ├── query.py       # Read commands (seek, survey, brief, herald, curation, derived)
│       ├── write.py       # Write commands (gather, distill, reforge, cleave, deskeleton, project)
│       ├── kg.py          # KG proposal commands (extract, review, accept, reject)
│       ├── config.py      # Config commands (wizard, tune, drawbridge)
│       ├── ops.py         # Ops commands (armory, garrison, parley, raise, ni)
│       └── internal.py    # Internal commands (hook, instructions)
└── parallel_benchmarks.py # Parallel benchmark utilities
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
- **Adding a service method**: appropriate `swampcastle/services/*.py` (or `services/vault/service.py`), add Pydantic I/O models in `swampcastle/models/`
- **Adding a storage backend**: subclass `CollectionStore`/`GraphStore` in `swampcastle/storage/`, add factory
- **Changing search**: `swampcastle/services/search.py` and `swampcastle/retrieval/hybrid.py`
- **Modifying mining**: `swampcastle/mining/miner.py` (files) or `swampcastle/mining/convo.py` (conversations)
- **Configuration**: `swampcastle/settings.py` — add field to `CastleSettings`
- **CLI commands**: `swampcastle/cli/commands/` — add handler in the appropriate concern file, wire in `cli/main.py` and re-export in `cli/commands/__init__.py`
- **Audit artifacts**: `swampcastle/audit/` — file-based overlay (curation, derived cards, origin manifests)
- **KG proposals**: `swampcastle/services/kg_proposals.py` + `swampcastle/mining/extractors.py`
- **Typed records**: `swampcastle/models/record.py` (RecordEnvelope, RecordKind) + `swampcastle/services/vault/service.py` (add_record, tombstone, gc)
- **AAAK dialect**: `swampcastle/dialect.py` + `swampcastle/services/vault/distill.py` (DistillEngine)
