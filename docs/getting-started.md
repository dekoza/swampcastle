# Getting started

## Prerequisites

- Python 3.11+
- local disk space for your castle data
- first-run ONNX model download for the default embedder (~87 MB, cached)

## Install

```bash
pip install swampcastle
```

Optional extras:

```bash
pip install 'swampcastle[server]'    # sync server
pip install 'swampcastle[postgres]'  # PostgreSQL backend
pip install 'swampcastle[gpu]'       # sentence-transformers embedder support
pip install 'swampcastle[chroma]'    # legacy migration tooling only
```

## First local castle

On first use, SwampCastle creates a default global runtime config at `~/.swampcastle/config.json` and uses the local Lance backend. If you want to change runtime backend or storage settings, run:

```bash
swampcastle wizard
```

`wizard` can also store your self identity (`name`, `nickname`, `facts`) in `~/.swampcastle/entity_registry.json` for contributor resolution during ingest.

### 1. Prepare project structure

```bash
swampcastle project ~/projects/myapp --team dekoza sarah
```

`project` writes `.swampcastle.yaml` for the target project. It prepares room routing for ingest but does not ingest files by itself. If a legacy `swampcastle.yaml` exists, it is migrated automatically.

If you pass `--team`, SwampCastle stores shared contributor identifiers in the project config so later ingest can tag drawers with a best-effort `contributor` value.

### 2. Ingest project files

```bash
swampcastle gather ~/projects/myapp
```

Useful flags:

```bash
swampcastle gather ~/projects/myapp --wing myapp
swampcastle gather ~/projects/myapp --dry-run
swampcastle gather ~/projects/myapp --include-ignored docs/generated
```

### 3. Search what you stored

```bash
swampcastle seek "auth migration"
swampcastle seek "billing retry policy" --wing myapp --room billing
swampcastle seek "auth migration" --contributor dekoza
```

### 4. Inspect the current shape

```bash
swampcastle survey
```

## Conversation ingest

Conversation mining uses the same command with `--mode convos`:

```bash
swampcastle gather ~/chat-exports --mode convos --wing myapp
```

If the source directory also contains `.swampcastle.yaml` with a `team` list, conversation ingest uses the same best-effort contributor tagging as project-file ingest.

If you want broader extraction instead of exchange-pair chunking:

```bash
swampcastle gather ~/chat-exports --mode convos --extract general --wing myapp
```

If your exports contain multiple sessions per file:

```bash
swampcastle cleave ~/chat-exports
```

## Connect an AI client over MCP

### Claude Code

```bash
claude mcp add swampcastle -- swampcastle-mcp
```

### Gemini CLI

```bash
gemini mcp add swampcastle swampcastle-mcp --scope user
```

### Manual startup

```bash
swampcastle drawbridge run
# or
swampcastle-mcp
```

To print the recommended setup command:

```bash
swampcastle drawbridge
```

## Enable sync

Hub:

```bash
pip install 'swampcastle[server]'
swampcastle serve --host 0.0.0.0 --port 7433
```

Client:

```bash
swampcastle sync --server http://homeserver:7433
```

The current CLI performs one sync exchange per invocation. Continuous loop flags were removed because that mode was never implemented.

## PostgreSQL backend

SwampCastle defaults to local LanceDB + SQLite. To route new Castle instances through PostgreSQL instead:

```bash
export SWAMPCASTLE_BACKEND=postgres
export SWAMPCASTLE_DATABASE_URL=postgresql://user:pass@host:5432/swampcastle
```

Then the same high-level commands (`survey`, `seek`, MCP, sync server) use PostgreSQL-backed stores.

## Next reading

- [Architecture](architecture.md)
- [CLI reference](cli.md)
- [Configuration](configuration.md)
- [Mining](mining.md)
- [MCP server](mcp.md)
- [Sync](sync.md)
- [Python API](python-api.md)
