# Architecture

SwampCastle v4 is built around explicit boundaries:

```text
CLI / MCP / Sync
      ↓
   Castle
      ├── CatalogService
      ├── SearchService
      ├── VaultService
      └── GraphService
      ↓
CollectionStore + GraphStore + WalWriter
```

The old flat module graph is gone. The system now routes through a `Castle` context object plus storage contracts.

## Core concepts

### Castle

`Castle` owns one configured collection store, one graph store, and the service layer that sits on top of them.

```python
with Castle(settings, factory) as castle:
    castle.search.search(...)
    castle.vault.add_drawer(...)
    castle.graph.kg_add(...)
```

### Services

| Service | Responsibility | Dependencies |
|---|---|---|
| `CatalogService` | Status, wings, rooms, taxonomy, AAAK spec | `CollectionStore` |
| `SearchService` | Semantic search and duplicate detection | `CollectionStore` |
| `VaultService` | Drawer writes, deletes, diary writes | `CollectionStore`, `WalWriter` |
| `GraphService` | Knowledge-graph ops and castle graph traversal | `GraphStore`, `CollectionStore`, `WalWriter` |

### Storage contracts

Two abstract contracts define the storage boundary:

- `CollectionStore` — document + vector storage
- `GraphStore` — entity / relationship storage

Factory implementations:

| Factory | Collection | Graph | Typical use |
|---|---|---|---|
| `InMemoryStorageFactory` | in-memory | in-memory | unit tests |
| `LocalStorageFactory` | LanceDB | SQLite | local workstation |
| `PostgresStorageFactory` | pgvector | PostgreSQL tables | server / shared DB |

The routing helper is `factory_from_settings(settings)`.

## Spatial memory model

SwampCastle still uses the castle metaphor because it maps cleanly onto metadata filters:

```text
WING
  └── ROOM
        └── DRAWER
```

- **Wing** — project, person, or domain
- **Room** — topic within a wing
- **Drawer** — verbatim text chunk

The graph layer builds on top of that metadata to find:

- shared rooms across wings
- cross-domain tunnels
- graph traversal paths

## Write-ahead log

Mutating service operations write to a WAL before they touch storage.

Current WAL-backed operations include:
- drawer writes
- drawer deletes
- knowledge-graph fact additions
- knowledge-graph invalidations
- diary writes

This gives you a plain JSONL audit trail under `settings.wal_path`.

## Sync model

Sync is implemented as a `SyncEngine` over a `CollectionStore`.

Each record carries:
- `node_id`
- `seq`
- `updated_at`

Version vectors live next to `castle_path` in `version_vector.json`, even when the collection backend is PostgreSQL.

## MCP boundary

The MCP server is thin:

1. create `CastleSettings`
2. build a factory via `factory_from_settings()`
3. construct `Castle`
4. register 19 tools from Pydantic models
5. translate JSON-RPC requests into service calls

The tool registry lives in `swampcastle/mcp/tools.py`.

## Async boundary

`AsyncCastle` wraps a synchronous `Castle` and delegates through `anyio.to_thread.run_sync()`. That keeps the core logic synchronous while still allowing async entry points such as FastAPI.

## What v4 intentionally removed

The following patterns are no longer the architectural source of truth:

- direct module-to-module global state
- ChromaDB as the default storage backend
- old `searcher`, `layers`, `palace`, and `knowledge_graph` entry points
- hand-written MCP JSON schemas detached from the actual models

Those older names still appear in migration docs because users may be upgrading from MemPalace-era code, but the v4 architecture itself no longer depends on them.
