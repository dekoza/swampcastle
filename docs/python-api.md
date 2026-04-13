# Python API

SwampCastle v4 is centered on `Castle`, Pydantic command/query models, and storage factories.

## Recommended entry point: Castle

```python
from swampcastle.castle import Castle
from swampcastle.models import AddDrawerCommand, SearchQuery
from swampcastle.settings import CastleSettings
from swampcastle.storage import factory_from_settings

settings = CastleSettings(_env_file=None)
factory = factory_from_settings(settings)

with Castle(settings, factory) as castle:
    castle.vault.add_drawer(
        AddDrawerCommand(
            wing="myapp",
            room="auth",
            content="We switched providers because token rotation got simpler.",
        )
    )

    result = castle.search.search(SearchQuery(query="provider switch", wing="myapp"))
    print(result.results)
```

## Settings

```python
from swampcastle.settings import CastleSettings

settings = CastleSettings(_env_file=None)
settings.castle_path
settings.collection_name
settings.backend
settings.database_url
settings.kg_path
settings.wal_path
settings.config_dir
```

You can also construct settings explicitly:

```python
settings = CastleSettings(
    _env_file=None,
    castle_path="/srv/swampcastle/castle",
    backend="postgres",
    database_url="postgresql://user:pass@localhost:5432/swampcastle",
)
```

## Factories

### Config-driven routing

```python
from swampcastle.storage import factory_from_settings

factory = factory_from_settings(settings)
```

### Direct factories

```python
from swampcastle.storage.lance import LocalStorageFactory
from swampcastle.storage.memory import InMemoryStorageFactory
from swampcastle.storage.postgres import PostgresStorageFactory

local = LocalStorageFactory(settings.castle_path)
memory = InMemoryStorageFactory()
postgres = PostgresStorageFactory("postgresql://user:pass@localhost:5432/swampcastle")
```

## Search

```python
from swampcastle.models import SearchQuery

result = castle.search.search(
    SearchQuery(query="billing retry policy", wing="myapp", room="billing", limit=5)
)
```

Related model types:
- `SearchQuery`
- `SearchResponse`
- `SearchHit`
- `DuplicateCheckQuery`
- `DuplicateCheckResult`

## Drawer writes

```python
from swampcastle.models import AddDrawerCommand, DeleteDrawerCommand

castle.vault.add_drawer(
    AddDrawerCommand(
        wing="myapp",
        room="auth",
        content="Rotation now happens server-side.",
        source_file="notes/auth.md",
        added_by="python-api",
    )
)

castle.vault.delete_drawer(DeleteDrawerCommand(drawer_id="drawer_myapp_auth_1234"))
```

Diary helpers live on the same service:

```python
from swampcastle.models.diary import DiaryWriteCommand
from swampcastle.services.vault import DiaryReadQuery

castle.vault.diary_write(DiaryWriteCommand(agent_name="reviewer", entry="Found a sync race."))
castle.vault.diary_read(DiaryReadQuery(agent_name="reviewer"))
```

## Knowledge graph

High-level graph API:

```python
castle.graph.kg_add(subject="Kai", predicate="works_on", obj="Orion")
castle.graph.kg_query(entity="Kai")
castle.graph.kg_invalidate(subject="Kai", predicate="works_on", obj="Orion")
castle.graph.kg_timeline(entity="Kai")
castle.graph.kg_stats()
```

If you need the raw stores directly:

```python
from swampcastle.storage.sqlite_graph import SQLiteGraph
from swampcastle.storage.postgres import PostgresGraphStore
```

## Catalog / metadata

```python
status = castle.catalog.status()
wings = castle.catalog.list_wings()
rooms = castle.catalog.list_rooms("myapp")
taxonomy = castle.catalog.get_taxonomy()
aaak_spec = castle.catalog.get_aaak_spec()
```

## Sync

```python
from swampcastle.sync import SyncEngine
from swampcastle.sync_client import SyncClient
from swampcastle.sync_meta import get_identity

identity = get_identity(str(settings.config_dir))
engine = SyncEngine(
    castle._collection,
    identity=identity,
    vv_path=str(settings.castle_path / "version_vector.json"),
)
client = SyncClient("http://homeserver:7433")
summary = client.sync(engine)
```

## Mining helpers

```python
from swampcastle.mining.miner import mine
from swampcastle.mining.convo import mine_convos

mine("/path/to/project", "/path/to/castle")
mine_convos("/path/to/exports", "/path/to/castle", wing="myapp")
```

Both functions also accept `storage_factory=` if you need to inject a backend explicitly.

## MCP server

```python
from swampcastle.mcp.server import create_handler
from swampcastle.mcp.tools import register_tools
```

Typical usage is still the CLI entry point:

```bash
swampcastle drawbridge run
```

## Legacy note

The following old MemPalace-era modules are no longer the recommended API surface:
- `searcher`
- `layers`
- `palace`
- `knowledge_graph` (as a top-level public module)
- `config`

Use `Castle`, `CastleSettings`, the Pydantic models, and storage factories instead.
