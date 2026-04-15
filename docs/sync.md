# Sync

SwampCastle sync is a hub-and-spoke replication layer built on top of `SyncEngine` and `SyncClient`.

## What sync operates on

Sync exchanges drawer records from the active `CollectionStore` backend.

Today that means:
- local LanceDB collections
- PostgreSQL / pgvector collections

ChromaDB is still not a supported runtime sync backend.

## Data carried with each record

Each synced record carries:

- `document`
- `metadata`
- `embedding` when the source backend stores one

Each stored record also includes sync metadata:

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

Sync requests and responses negotiate HTTP gzip automatically. Large push and pull payloads are compressed on the wire when both sides support it.

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

### Optional token authentication

The sync server supports optional Bearer-token authentication.
Set `SWAMPCASTLE_SYNC_API_KEY` to a random secret before starting the server:

```bash
export SWAMPCASTLE_SYNC_API_KEY=$(openssl rand -hex 32)
swampcastle serve --host 0.0.0.0 --port 7433
```

When the key is set every sync endpoint (`/sync/status`, `/sync/push`,
`/sync/pull`) requires the header:

```
Authorization: Bearer <your-key>
```

The `/health` endpoint remains unauthenticated (for load-balancer probes).
Requests without the header, or with the wrong token, receive `401`.

The sync client reads the same env var automatically:

```bash
export SWAMPCASTLE_SYNC_API_KEY=<same-key>
swampcastle sync --server http://homeserver:7433
```

Token comparison uses `hmac.compare_digest()` (constant-time) to prevent
timing attacks.

**Without `SWAMPCASTLE_SYNC_API_KEY` set**, the server is open — fine for a
trusted private LAN, insecure for internet-facing deployments.

### Network-level protection

- Put the server behind TLS / a reverse proxy on untrusted networks.
- Or use an SSH tunnel.
- Or keep it on a trusted LAN only.

**Note:** the KG (knowledge graph, SQLite) is not replicated by sync — only
the drawer collection is transferred between nodes.

## Notes on backend routing

The sync server now routes through `factory_from_settings()` instead of hardcoding LanceDB. That keeps sync aligned with the same backend configuration used by Castle, MCP, and the main CLI.
