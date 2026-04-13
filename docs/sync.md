# Sync

SwampCastle sync is a hub-and-spoke replication layer built on top of `SyncEngine` and `SyncClient`.

## What sync operates on

Sync exchanges drawer records from the active `CollectionStore` backend.

Today that means:
- local LanceDB collections
- PostgreSQL / pgvector collections

ChromaDB is still not a supported runtime sync backend.

## Data carried with each record

Each stored record includes sync metadata:

- `node_id`
- `seq`
- `updated_at`

These are used to compute version vectors and conflict resolution.

## Version vectors

Version vectors are persisted locally at:

```text
<castle_path>/version_vector.json
```

That remains true even in PostgreSQL mode.

## Conflict resolution

When the same drawer ID exists on both sides:

1. later `updated_at` wins
2. if timestamps tie, lexicographically higher `node_id` wins

That rule is simple, deterministic, and already covered by tests.

## Start a sync server

```bash
pip install 'swampcastle[server]'
swampcastle serve --host 0.0.0.0 --port 7433
```

Alias:

```bash
swampcastle garrison --host 0.0.0.0 --port 7433
```

Endpoints:

| Method | Path | Meaning |
|---|---|---|
| `GET` | `/health` | liveness check |
| `GET` | `/sync/status` | node id, version vector, drawer count |
| `POST` | `/sync/push` | accept a pushed change set |
| `POST` | `/sync/pull` | return changes the caller has not seen |

## Run a client sync

```bash
swampcastle sync --server http://homeserver:7433
```

Alias:

```bash
swampcastle parley --server http://homeserver:7433
```

`--dry-run` is wired.

The CLI performs a single sync exchange per invocation. Continuous loop flags were removed because they were never implemented.

## Python API

```python
from swampcastle.castle import Castle
from swampcastle.settings import CastleSettings
from swampcastle.storage import factory_from_settings
from swampcastle.sync import SyncEngine
from swampcastle.sync_client import SyncClient
from swampcastle.sync_meta import get_identity

settings = CastleSettings(_env_file=None)
factory = factory_from_settings(settings)

with Castle(settings, factory) as castle:
    engine = SyncEngine(
        castle._collection,
        identity=get_identity(str(settings.config_dir)),
        vv_path=str(settings.castle_path / "version_vector.json"),
    )
    client = SyncClient("http://homeserver:7433")
    summary = client.sync(engine)
```

## Security

The built-in sync server is plain HTTP with no authentication.

That means:
- put it behind TLS / a reverse proxy on untrusted networks
- or use an SSH tunnel
- or keep it on a trusted LAN only

## Notes on backend routing

The sync server now routes through `factory_from_settings()` instead of hardcoding LanceDB. That keeps sync aligned with the same backend configuration used by Castle, MCP, and the main CLI.
