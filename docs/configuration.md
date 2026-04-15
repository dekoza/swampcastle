# Configuration

SwampCastle v4 uses `CastleSettings` from `swampcastle.settings`.

## Primary settings

```python
from swampcastle.settings import CastleSettings

settings = CastleSettings(_env_file=None)
```

Fields:

| Field | Type | Default | Notes |
|---|---|---|---|
| `castle_path` | `Path` | `~/.swampcastle/castle` | local data directory and sync vector location |
| `collection_name` | `str` | `swampcastle_chests` | collection / table name |
| `backend` | `lance \| postgres \| chroma` | `lance` | `chroma` is migration-only in v4 |
| `database_url` | `str \| None` | `None` | required for `backend=postgres` |
| `embedder` | `str` | `onnx` | active embedder backend / model selector; `onnx` is the canonical CPU-only path |
| `embedder_model` | `str \| None` | `None` | optional model override; mainly useful for Ollama or explicit HF model names |
| `embedder_device` | `str \| None` | `None` | optional device override passed into embedder config (e.g. `cpu`, `cuda`) |
| `embedder_options` | `dict[str, Any]` | `{}` | raw embedder option bag merged into `embedder_config`; supports fields like `base_url`, `timeout`, `device` |

Computed fields:

| Field | Derived from |
|---|---|
| `embedder_config` | normalized config dict consumed by `get_embedder()` |
| `kg_path` | `castle_path.parent / "knowledge_graph.sqlite3"` |
| `wal_path` | `castle_path.parent / "wal"` |
| `config_dir` | `castle_path.parent` |

## Environment variables

`CastleSettings` uses the `SWAMPCASTLE_` prefix.

Common variables:

| Variable | Meaning |
|---|---|
| `SWAMPCASTLE_CASTLE_PATH` | override `castle_path` |
| `SWAMPCASTLE_COLLECTION_NAME` | override collection / table name |
| `SWAMPCASTLE_BACKEND` | `lance`, `postgres`, or `chroma` |
| `SWAMPCASTLE_DATABASE_URL` | PostgreSQL DSN |
| `SWAMPCASTLE_EMBEDDER` | embedder name |
| `SWAMPCASTLE_EMBEDDER_MODEL` | embedder model override |
| `SWAMPCASTLE_EMBEDDER_DEVICE` | device override |
| `SWAMPCASTLE_ONNX_CACHE` | cache directory for the default ONNX model |
| `SWAMPCASTLE_EMBEDDER_OPTIONS` | JSON-encoded raw option bag for advanced cases |
| `SWAMPCASTLE_SOURCE_DIR` | default source directory for `cleave` |

## Local mode

Default local routing:

```bash
export SWAMPCASTLE_BACKEND=lance
export SWAMPCASTLE_CASTLE_PATH=~/.swampcastle/castle
```

This resolves to:
- collection store: LanceDB
- graph store: SQLite

## PostgreSQL mode

```bash
export SWAMPCASTLE_BACKEND=postgres
export SWAMPCASTLE_DATABASE_URL=postgresql://user:pass@host:5432/swampcastle
```

This resolves to:
- collection store: pgvector-backed PostgreSQL table
- graph store: PostgreSQL tables

`castle_path` still matters in PostgreSQL mode because version vectors and other local artifacts are stored next to it.

## JSON settings files

`CastleSettings` can merge values from a JSON file, but only if you pass `_json_file=` explicitly in Python:

```python
settings = CastleSettings(_env_file=None, _json_file="/path/to/config.json")
```

That merge order is:
1. explicit kwargs
2. environment variables
3. JSON file values
4. defaults

The CLI now auto-creates and auto-loads `~/.swampcastle/config.json` on first use. The default runtime backend is Lance and the default embedder is canonical CPU-only ONNX MiniLM. To edit that runtime configuration explicitly, run:

```bash
swampcastle wizard
```

The same runtime directory may also contain:
- `entity_registry.json` — your self identity plus known people/projects
- `aaak_entities.md` — AAAK-oriented entity aliases derived from the registry

Project-local mining config lives separately in `.swampcastle.yaml`. That file can include a shared `team` list used for contributor tagging during ingest.

Global and project-level mining ignore files

- Per-project: create `.swampcastleignore` in project directory (or subdirectories) to exclude files from AI indexing while keeping them in version control. Syntax mirrors `.gitignore`: supports `!` negation, anchored paths, and trailing `/` for directories.
- Global: create `~/.swampcastleignore` to apply user-wide ignore rules across all projects.

Precedence (when deciding to skip a file):
1. Project `.swampcastleignore` rules (closest ancestor directory wins)
2. Global `~/.swampcastleignore`
3. `.gitignore`

Force-includes (CLI `--include-ignored`) still override these ignores for one-off ingests.

## Recommended backend routing

Use `factory_from_settings()` rather than importing a backend directly when you want configuration-driven behavior:

```python
from swampcastle.settings import CastleSettings
from swampcastle.storage import factory_from_settings

settings = CastleSettings(_env_file=None)
factory = factory_from_settings(settings)
```

Use a concrete factory directly when you want to pin the backend in code:

```python
from swampcastle.storage.lance import LocalStorageFactory
from swampcastle.storage.postgres import PostgresStorageFactory
```

## Validation behavior

Name validation for wings / rooms / related fields comes from the Pydantic models in `swampcastle.models.drawer`:

- non-empty string
- max length 128
- no `..`, `/`, `\\`
- no null bytes
- restricted character set

Content fields enforce:
- non-empty text
- max length 100,000
- no null bytes

## Example: explicit PostgreSQL configuration in Python

```python
from swampcastle.settings import CastleSettings
from swampcastle.storage import factory_from_settings

settings = CastleSettings(
    _env_file=None,
    backend="postgres",
    database_url="postgresql://user:pass@localhost:5432/swampcastle",
    castle_path="/srv/swampcastle/castle",
)
factory = factory_from_settings(settings)
```
