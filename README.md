<div align="center">

<img src="assets/Swamp.webp" alt="SwampCastle" width="420">

# SwampCastle

Built on the foundations of [MemPalace](https://github.com/MemPalace/mempalace).

**The fourth one stayed up.**

Local, searchable memory for AI assistants.

[![][version-shield]][release-link]
[![][python-shield]][python-link]
[![][license-shield]][license-link]

</div>

---

## What SwampCastle is

SwampCastle v4 stores verbatim memory in a collection backend and structured facts in a graph backend.

- **Local mode:** LanceDB + SQLite
- **Server mode:** PostgreSQL + pgvector
- **Test mode:** in-memory stores

The public architecture is:

```text
CLI / MCP / Sync
      ↓
   Castle
      ├── CatalogService
      ├── SearchService
      ├── VaultService
      └── GraphService
      ↓
CollectionStore + GraphStore
```

The spatial model is still the same:

```text
WING (project / person / domain)
  └── ROOM (topic)
        └── DRAWER (verbatim text chunk)
```

## Install

```bash
pip install swampcastle
```

**Requirements**

- Python 3.11+
- first-run ONNX model download for the default embedder (~87 MB, cached locally)

Optional extras:

```bash
pip install 'swampcastle[server]'    # FastAPI + uvicorn for sync server
pip install 'swampcastle[postgres]'  # PostgreSQL + pgvector backend
pip install 'swampcastle[gpu]'       # sentence-transformers embedder support
pip install 'swampcastle[chroma]'    # legacy ChromaDB tooling for migration only
```

## Quick start

Before doing anything else, SwampCastle will create a default global runtime config at `~/.swampcastle/config.json` the first time you use the CLI. The default backend is Lance. If you want to change backend or storage settings, run:

```bash
swampcastle wizard
```

The wizard can also store your own identity in `~/.swampcastle/entity_registry.json` so SwampCastle can recognize you by name or nickname during ingest.

If you stick with the canonical CPU ONNX embedder and want to rerun the local performance benchmark later, use:

```bash
swampcastle tune
```

### 1. Prepare a project

```bash
swampcastle project ~/projects/myapp --team dekoza sarah
```

`project` creates project-local mining config in `.swampcastle.yaml`. It does not ingest files by itself. If an older `swampcastle.yaml` exists, SwampCastle will migrate it to the hidden filename and tell you.

The optional `team` list lets ingest tag drawers with a best-effort `contributor` identity from git history.

### 2. Ingest files

```bash
swampcastle gather ~/projects/myapp
```

Conversation exports use the same command:

```bash
swampcastle gather ~/chat-exports --mode convos --wing myapp
```

### 3. Search

```bash
swampcastle seek "why did we switch auth providers"
swampcastle seek "pricing" --wing myapp --room billing
swampcastle seek "auth migration" --contributor dekoza
```

### 4. Inspect the castle

```bash
swampcastle survey
swampcastle brief --wing myapp
```

Use `brief` (alias: `minstrel`) when you want a human-readable wing summary. Use `herald` when you want the strict SwampCastle memory-use protocol for agent instructions.

## MCP setup

Show the setup command:

```bash
swampcastle drawbridge
```

Run the server directly:

```bash
swampcastle drawbridge run
# or
swampcastle-mcp
```

Example Claude Code setup:

```bash
claude mcp add swampcastle -- swampcastle-mcp
```

Example Gemini CLI setup:

```bash
gemini mcp add swampcastle swampcastle-mcp --scope user
```

See [docs/mcp.md](docs/mcp.md).

## Python API

Recommended entry point:

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
            content="We switched providers because rotation and local testing got simpler.",
        )
    )

    result = castle.search.search(SearchQuery(query="provider switch", wing="myapp"))
    print(result.results)
```

For low-level backend access, see [docs/python-api.md](docs/python-api.md).

## Sync

Hub:

```bash
pip install 'swampcastle[server]'
swampcastle serve --host 0.0.0.0 --port 7433
```

Client:

```bash
swampcastle sync --server http://homeserver:7433
```

SwampCastle sync now works against the configured collection backend. Version vectors are still stored locally alongside `castle_path`.

See [docs/sync.md](docs/sync.md).

## Legacy Chroma migration

SwampCastle can raise a legacy ChromaDB palace into the v4 local castle layout:

```bash
swampcastle raise --source-palace ~/.mempalace/palace
```

By default the target is your configured `castle_path` (usually `~/.swampcastle/castle`).
You can override it:

```bash
swampcastle raise --source-palace ~/.mempalace/palace --target-castle /tmp/swampcastle/castle
swampcastle raise --source-palace ~/.mempalace/palace --dry-run
```

The source palace is left untouched. Drawer data is imported into LanceDB, and common sidecar files such as the knowledge graph and sync identity files are copied when present.

## Current state of the CLI

The core ingest / search / MCP / sync path is working:

- `project`
- `gather` / `mine`
- `seek` / `search`
- `survey` / `status`
- `drawbridge` / `mcp`
- `serve` / `sync`

Some maintenance commands are still being rebuilt and are intentionally thin right now:

- `reforge` / `reindex`
- `distill` / `compress`

The docs call that out explicitly where relevant instead of pretending those flows are complete.

## Documentation

| Document | Contents |
|----------|----------|
| [Getting started](docs/getting-started.md) | First ingest, first search, MCP setup |
| [Architecture](docs/architecture.md) | Castle, services, storage contracts, backends |
| [CLI reference](docs/cli.md) | Real command surface and aliases |
| [Configuration](docs/configuration.md) | `CastleSettings`, env vars, backend selection |
| [Mining](docs/mining.md) | Project + conversation ingest |
| [Searching](docs/searching.md) | CLI and Python search flows |
| [Knowledge graph](docs/kg.md) | Graph service and direct stores |
| [MCP server](docs/mcp.md) | Setup and tool catalog |
| [Sync](docs/sync.md) | Hub / spoke sync model |
| [Hooks](docs/hooks.md) | Hook protocol and supported harnesses |
| [Python API](docs/python-api.md) | Programmatic usage |
| [AAAK dialect](docs/aaak.md) | Experimental compression layer |
| [Migration](docs/migration.md) | Moving from MemPalace |
| [Changelog](CHANGELOG.md) | Release history and notable changes |
| [Notices](NOTICES.md) | Security notes and release errata |

## License

MIT — see [LICENSE](LICENSE).

<!-- Link Definitions -->
[version-shield]: https://img.shields.io/github/v/release/dekoza/swampcastle?style=flat-square&labelColor=0a0e14
[release-link]: https://github.com/dekoza/swampcastle/releases
[python-shield]: https://img.shields.io/badge/python-3.11%2B-7dd8f8?style=flat-square&labelColor=0a0e14&logo=python&logoColor=7dd8f8
[python-link]: https://www.python.org/
[license-shield]: https://img.shields.io/badge/license-MIT-b0e8ff?style=flat-square&labelColor=0a0e14
[license-link]: https://github.com/dekoza/swampcastle/blob/main/LICENSE
