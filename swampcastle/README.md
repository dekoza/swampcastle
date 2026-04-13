# swampcastle/ package map

This package is the v4 implementation.

## Primary modules

| Path | Purpose |
|---|---|
| `castle.py` | `Castle` and `AsyncCastle` context objects |
| `settings.py` | `CastleSettings` |
| `errors.py` | typed error hierarchy |
| `wal.py` | write-ahead log |
| `models/` | Pydantic request / response models |
| `services/` | catalog, search, vault, graph service layer |
| `storage/base.py` | `CollectionStore` and `GraphStore` contracts |
| `storage/memory.py` | in-memory backends for tests |
| `storage/lance.py` | local LanceDB collection + SQLite graph factory |
| `storage/sqlite_graph.py` | direct SQLite graph store |
| `storage/postgres.py` | PostgreSQL + pgvector backends |
| `mcp/` | JSON-RPC MCP server and tool registry |
| `cli/` | argparse CLI entry points |
| `mining/` | project and conversation ingest |
| `sync.py` | sync engine and version-vector logic |
| `sync_client.py` | HTTP sync client |
| `sync_server.py` | FastAPI sync server |
| `sync_meta.py` | node identity + seq metadata |
| `dialect.py` | AAAK experimental compression / summary format |
| `dedup.py` | backend-agnostic duplicate cleanup utility |
| `migrate.py` | legacy migration / recovery tooling under replacement |
| `hooks_cli.py` | hook protocol implementation |
| `instructions_cli.py` | packaged instruction text output |

## Design rule

Most new code should go through:

```text
Castle -> Services -> Storage contracts
```

If you find yourself re-introducing direct old-style module helpers such as `searcher`, `layers`, or `palace`, you are moving the codebase backwards.
