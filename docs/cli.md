# CLI reference

Global options:

```bash
swampcastle [--palace PATH] [--backend {lance,postgres,chroma}] <command> ...
```

Aliases are important in v4: the castle-themed verbs are primary, and the older MemPalace-style verbs remain as aliases.

## build / init

Preview room and entity detection for a project directory.

```bash
swampcastle build <dir> [--yes]
swampcastle init <dir> [--yes]
```

Current behavior:
- scans folder names to infer rooms
- scans content to infer people / projects
- prints what it found
- does **not** ingest files on its own

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

Examples:

```bash
swampcastle gather ~/projects/myapp
swampcastle gather ~/chat-exports --mode convos --wing myapp
swampcastle gather ~/projects/myapp --dry-run --limit 10
```

## seek / search

Semantic search.

```bash
swampcastle seek <query> [--wing NAME] [--room NAME] [--results N]
swampcastle search <query> [--wing NAME] [--room NAME] [--results N]
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

Print the protocol / status context for the current castle.

```bash
swampcastle herald [--wing NAME]
swampcastle wake-up [--wing NAME]
```

Current behavior is status-oriented. The old layer-based wake-up stack no longer exists as the public architecture.

## cleave / split

Split transcript mega-files into smaller session files.

```bash
swampcastle cleave <dir> [--output-dir DIR] [--dry-run] [--min-sessions N]
swampcastle split <dir> [--output-dir DIR] [--dry-run] [--min-sessions N]
```

## distill / compress

AAAK-related command.

```bash
swampcastle distill [--wing NAME] [--dry-run] [--config PATH]
swampcastle compress [--wing NAME] [--dry-run] [--config PATH]
```

Honest status: this command is still thin in v4. It reports what would be processed, but it is not yet a finished end-to-end compression pipeline.

## raise / migrate

Migration entry point.

```bash
swampcastle raise
swampcastle migrate
```

Honest status: the CLI command currently prints migration guidance. The legacy standalone `swampcastle.migrate` module still contains old Chroma-oriented recovery logic and is being replaced.

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

Parser flags also exist for `--auto` and `--interval`, but they are not wired into a loop yet.

## hook run (internal)

Internal hook bridge used by shell / harness integrations.

```bash
swampcastle hook run --hook {session-start,stop,precompact} --harness {claude-code,codex}
```

## instructions (internal)

Print packaged instruction text.

```bash
swampcastle instructions {init,search,mine,help,status}
```

## ni

Hidden easter egg.

```bash
swampcastle ni
```
