# Architecture

## Overview

SwampCastle v4 uses a layered architecture: Castle context → Services → Storage backends.

```
User → CLI / MCP Server → Castle (context)
                            ├── CatalogService → CollectionStore
                            ├── SearchService  → CollectionStore
                            ├── VaultService   → CollectionStore + WalWriter
                            └── GraphService   → GraphStore + CollectionStore + WalWriter
```

## Storage backends

Two abstract contracts:
- **CollectionStore** — document + vector storage (drawers)
- **GraphStore** — entity-relationship graph (knowledge graph)

Three factory implementations:

| Factory | CollectionStore | GraphStore | Use case |
|---------|----------------|------------|----------|
| `InMemoryStorageFactory` | Dict-based | Dict-based | Unit tests |
| `LocalStorageFactory` | LanceDB | SQLite | Production (local) |
| `PostgresStorageFactory` | pgvector | SQL tables | Production (server) |

The `Castle` constructor takes a `CastleSettings` and a `StorageFactory`. Callers decide which backend to use.

## Castle model

The castle organizes memories using a spatial metaphor. Each level of the hierarchy corresponds to metadata fields, which enables filtered search.

### Wings

A wing represents a person, project, or domain. Every memory belongs to exactly one wing.

### Rooms

A room is a specific topic within a wing. The same room name in multiple wings creates a tunnel (cross-wing connection).

### Halls

Memory type corridors — the same set exists in every wing:

| Hall | What it stores |
|------|---------------|
| `hall_facts` | Decisions made, choices locked in |
| `hall_events` | Sessions, milestones, debugging sessions |
| `hall_discoveries` | Breakthroughs, new insights |
| `hall_preferences` | Habits, likes, opinions |
| `hall_advice` | Recommendations and solutions |

### Tunnels

When the same room name appears in multiple wings, a tunnel connects them. This enables cross-domain queries.

## Services

Four role-based services, each with explicit dependencies:

| Service | Depends on | Responsibility |
|---------|-----------|----------------|
| `CatalogService` | `CollectionStore` | Read-only metadata: status, wings, rooms, taxonomy |
| `SearchService` | `CollectionStore`, `QuerySanitizer` | Semantic search, duplicate detection |
| `VaultService` | `CollectionStore`, `WalWriter` | Write operations: drawers, diary |
| `GraphService` | `GraphStore`, `CollectionStore`, `WalWriter` | KG ops, graph traversal, tunnels |

Services return Pydantic models. They raise `CastleError` subclasses on failure.

## MCP server

19 tools registered via `register_tools(castle)`. Each tool has:
- A Pydantic input model (schema auto-generated via `model_json_schema()`)
- A handler lambda that calls the appropriate service method

The JSON-RPC handler catches `CastleError` at the boundary and converts to error responses.

## Async

`AsyncCastle` wraps a sync `Castle`, delegating all calls to a thread pool via `anyio.to_thread.run_sync()`. Used by the FastAPI sync server and future async MCP.

## Configuration

`CastleSettings` (Pydantic `BaseSettings`) with priority: env vars (`SWAMPCASTLE_*`) > JSON config file > defaults.

Computed paths derive from `castle_path`:
- `kg_path` = `castle_path/../knowledge_graph.sqlite3`
- `wal_path` = `castle_path/../wal/`
- `config_dir` = `castle_path/..`

## Error handling

`CastleError` hierarchy with typed `code` attributes. Each boundary (MCP, CLI) has one try/except that catches `CastleError` and converts to the appropriate response format.
