# CLI reference

Global options:

```bash
swampcastle [--palace PATH] [--backend {lance,postgres,chroma}] <command> ...
```

SwampCastle auto-creates a default global runtime config at `~/.swampcastle/config.json` on first use. Use `swampcastle wizard` to edit that runtime config explicitly.

## project

Create or update project-local mining config for a directory.

```bash
swampcastle project <dir> [--yes] [--team NAME ...]
```

Current behavior:
- detects project rooms
- writes `.swampcastle.yaml`
- optionally stores a shared `team` list for contributor tagging
- does **not** ingest files on its own

## wizard

Edit global runtime configuration.

```bash
swampcastle wizard
```

The wizard edits `~/.swampcastle/config.json` and supports the default Lance backend or manual PostgreSQL configuration. It can also seed `~/.swampcastle/entity_registry.json` with your self identity and known people/projects.

## gather / mine

Ingest files into the configured collection backend.

```bash
swampcastle gather <dir> [options]
swampcastle mine <dir> [options]
```

Options:
- `--mode {projects,convos}`
- `--wing NAME`
- `--no-gitignore`
- `--include-ignored PATH` (repeatable)
- `--agent NAME`
- `--limit N`
- `--dry-run`
- `--extract {exchange,general}` (conversation mode)
- `--explain` — print skip reasons for files flagged by mining heuristics (useful for debugging why files were ignored)

Examples:

```bash
swampcastle gather ~/projects/myapp
swampcastle gather ~/chat-exports --mode convos --wing myapp
swampcastle gather ~/projects/myapp --dry-run --limit 10
```

## seek / search

Semantic search.

```bash
swampcastle seek <query> [--wing NAME] [--room NAME] [--contributor NAME] [--results N]
swampcastle search <query> [--wing NAME] [--room NAME] [--contributor NAME] [--results N]
```

## survey / status

Castle overview.

```bash
swampcastle survey
swampcastle status
```

Prints total drawers plus per-wing and per-room counts.

## drawbridge / mcp

MCP entry point.

```bash
swampcastle drawbridge
swampcastle mcp
```

Prints the recommended MCP setup command.

To actually run the JSON-RPC server:

```bash
swampcastle drawbridge run [--palace PATH]
# or
swampcastle-mcp
```

## herald / wake-up

Print the strict SwampCastle memory-use protocol.

```bash
swampcastle herald
swampcastle wake-up
```

This command is for behavior/policy, not for project state. It is intended for agent instructions or startup hooks, not for human project summaries.

## brief / minstrel

Print a wing-scoped briefing for prompt/context injection.

```bash
swampcastle brief --wing NAME
swampcastle minstrel --wing NAME
```

Current behavior includes:
- total drawers in the wing
- room counts
- tagged contributor counts when present
- unique source file count

## cleave / split

Split transcript mega-files into smaller session files.

```bash
swampcastle cleave <dir> [--output-dir DIR] [--dry-run] [--min-sessions N]
swampcastle split <dir> [--output-dir DIR] [--dry-run] [--min-sessions N]
```

## distill / compress

AAAK-related command.

```bash
swampcastle distill [--wing NAME] [--room NAME] [--config PATH]
swampcastle compress [--wing NAME] [--room NAME] [--config PATH]

# Preview is the default:
swampcastle distill

# Persist AAAK metadata updates explicitly:
swampcastle distill --apply

# Force preview even if you typed --apply in a script/template:
swampcastle distill --apply --dry-run
```

Honest status: this command is still thin in v4. It now defaults to preview mode.
You must pass `--apply` to persist AAAK metadata. That reflects the current
project policy: AAAK is optional and experimental, and raw verbatim drawers
remain the primary retrieval path.

## kg candidate review

Knowledge-graph proposal workflow.

```bash
# Preview extraction (default)
swampcastle kg extract

# Persist candidate proposals (not accepted facts)
swampcastle kg extract --apply

# Review proposals
swampcastle kg review

# Accept or reject a proposal
swampcastle kg accept <candidate-id>
swampcastle kg reject <candidate-id>
```

Honest status: this is the proposal-first skeleton only. `kg extract` creates
candidate triples, not accepted KG facts. You still need `kg accept` to write
facts into the canonical graph.

## raise / migrate

Raise a legacy ChromaDB palace into the v4 local castle layout.

```bash
swampcastle raise --source-palace ~/.mempalace/palace
swampcastle migrate --source-palace ~/.mempalace/palace
```

Options:
- `--source-palace PATH` — legacy Chroma palace directory (containing `chroma.sqlite3`)
- `--target-castle PATH` — target v4 castle directory (defaults to configured `castle_path`)
- `--dry-run` — inspect what would be migrated without writing anything

Behavior:
- reads legacy drawer data directly from Chroma's SQLite store
- writes the target in LanceDB layout
- preserves the source palace untouched
- copies common sidecar files (`knowledge_graph.sqlite3`, `identity.txt`, `node_id`, `seq`, `wal/`) when present

## reforge / reindex

Embedding maintenance entry point.

```bash
swampcastle reforge [--embedder NAME] [--device DEVICE] [--dry-run]
swampcastle reindex [--embedder NAME] [--device DEVICE] [--dry-run]
```

Honest status: this command is currently a scaffold. The full re-embed pipeline is not finished yet.

## armory / embedders

List known embedder configurations.

```bash
swampcastle armory
swampcastle embedders
```

## garrison / serve

Run the HTTP sync server.

```bash
swampcastle garrison [--host HOST] [--port PORT]
swampcastle serve [--host HOST] [--port PORT]
```

Requires:

```bash
pip install 'swampcastle[server]'
```

## parley / sync

Run one sync exchange against a server.

```bash
swampcastle parley --server URL [--dry-run]
swampcastle sync --server URL [--dry-run]
```

This command performs one sync exchange per invocation. There is no built-in continuous loop mode.

## hook run (internal)

Internal hook bridge used by shell / harness integrations. This command is gated and requires an explicit env guard.

```bash
SWAMPCASTLE_INTERNAL=1 swampcastle hook run --hook {session-start,stop,precompact} --harness {claude-code,codex}
```

## instructions (internal)

Print packaged instruction text. This command is gated and requires an explicit env guard.

```bash
SWAMPCASTLE_INTERNAL=1 swampcastle instructions {project,search,mine,help,status}
```

## ni

Hidden easter egg.

```bash
swampcastle ni
```
