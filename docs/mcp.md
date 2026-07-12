# MCP server

SwampCastle exposes 25 tools over JSON-RPC stdin/stdout.

Raw MCP discovery now advertises short tool names such as `status`, `search`, and `kg_query`.
Many MCP clients add their own server namespace on top, so you may still see rendered names
such as `swampcastle_search` in client UIs. For one compatibility release, legacy
`swampcastle_*` names remain callable as hidden aliases but are omitted from discovery.

## Start the server

Recommended:

```bash
swampcastle drawbridge run
# or
swampcastle-mcp
```

To print the recommended setup command for your current environment:

```bash
swampcastle drawbridge
```

With a custom castle path:

```bash
swampcastle drawbridge run --palace /path/to/castle
```

## Client setup

### Claude Code

```bash
claude mcp add swampcastle -- swampcastle-mcp
```

### Gemini CLI

```bash
gemini mcp add swampcastle swampcastle-mcp --scope user
```

## Server behavior

At startup the server:
1. loads `CastleSettings`
2. routes to a storage factory via `factory_from_settings()`
3. constructs a `Castle`
4. registers tools from `swampcastle.mcp.tools`
5. kicks off a background preload of the write path (see "Deploying while servers are live")
6. serves JSON-RPC over stdin/stdout

## Deploying while servers are live

The release act is `pipx reinstall swampcastle`, which **deletes and recreates the venv underneath any running MCP server**. On Linux the server keeps working for everything it has already imported (the deleted files stay mapped), but any import that resolves *after* the swap reads the mismatched new tree and throws — historically this broke `add_drawer`/`diary_write` mid-session with opaque `-32603` errors.

Hardening: at startup the server eagerly resolves every lazily-imported write-path module (`WRITE_PATH_MODULES` in `swampcastle/mcp/server.py`) and warms the embedder, in a daemon thread so `initialize` is never delayed. A server that finished its preload survives a venv swap for all normal tool traffic. Preload failures are logged to `~/.swampcastle/hook_state/mcp-server.log` and never fatal.

What the preload **cannot** cover:
- code paths added by the new release (the old server still runs old code — it just won't crash)
- a deploy landing in the first seconds of a server's life, before the preload finishes
- subprocess re-invocations (`swampcastle` CLI from hooks) — these always run the new tree and are unaffected by design

**Runbook:** after `pipx reinstall`, running sessions keep working but serve the *old* code. To pick up the new release, reconnect the MCP server (`/mcp` → reconnect in Claude Code) or restart the client session at your convenience — it's no longer urgent, just eventual.

## Tool catalog

### Catalog / status
- `status`
- `list_wings`
- `list_rooms`
- `get_taxonomy`
- `get_aaak_spec`

### Audit overlay reads
- `get_origin`
- `get_curation`
- `list_catalog_cards`

### Search
- `search`
- `check_duplicate`

### Drawer writes
- `add_drawer`
- `delete_drawer`

### Knowledge graph
- `kg_query`
- `kg_add`
- `kg_invalidate`
- `kg_timeline`
- `kg_stats`

### Castle graph navigation
- `traverse`
- `find_tunnels`
- `graph_stats`

### Agent diary
- `diary_write`
- `diary_read`

## Important request shapes

### get origin

`get_origin` uses the `OriginLookupQuery` model:

| Field | Type | Required |
|---|---|---|
| `origin_id` | string | exactly one of `origin_id` / `source_file` |
| `source_file` | string | exactly one of `origin_id` / `source_file` |

It returns the stored source-origin manifest when found.

### get curation

`get_curation` uses the `CurationQuery` model:

| Field | Type | Required |
|---|---|---|
| `wing` | string | no |

It returns local curation data:
- aliases
- tunnel policy
- available wing notes
- the requested wing note when `wing` is supplied and present

### list catalog cards

`list_catalog_cards` uses the `CatalogCardsQuery` model:

| Field | Type | Required |
|---|---|---|
| `wing` | string | yes |

It returns the rebuildable derived catalog cards currently stored for that wing.

### search

`search` uses the `SearchQuery` model:

| Field | Type | Required |
|---|---|---|
| `query` | string | yes |
| `limit` | integer | no |
| `wing` | string | no |
| `room` | string | no |
| `contributor` | string | no |
| `context` | string | no |
| `lexical_rerank` | boolean | no |
| `hybrid` | boolean | no |
| `explain` | boolean | no |

When `explain=true`, returned search hits may also include:
- `matched_via`
- `dense_similarity`
- `lexical_score`
- `boosts`
- `origin_id`
- `source_kind`
- `source_platform`

### add drawer

`add_drawer` uses `AddDrawerCommand`:

| Field | Type | Required |
|---|---|---|
| `wing` | string | yes |
| `room` | string | yes |
| `content` | string | yes |
| `source_file` | string | no |
| `added_by` | string | no |

### graph query

`kg_query` uses `KGQueryParams`:

| Field | Type | Required |
|---|---|---|
| `entity` | string | yes |
| `as_of` | string | no |
| `direction` | `outgoing \| incoming \| both` | no |

## Protocol expectations

The full protocol text (`SERVER_INSTRUCTIONS` in `swampcastle/mcp/protocol.py`) reaches the model through a delivery ladder:

1. **Primary — MCP `instructions`**: the `initialize` result carries the protocol; clients (Claude Code included) put it in the model's context automatically. Tool descriptions reinforce the ordering ("call status first, before any task work"; read-before-write pointers on the write tools).
2. **Secondary — the `status` digest**: a 5–10-line protocol gist inside the session digest, plus the staleness/activity data that makes querying worthwhile.
3. **Tertiary — hook-less fallback**: `swampcastle herald` prints the same text for clients with no instructions surface; a one-line CLAUDE.md/AGENTS.md pointer ("call status at session start") is all that should live in static agent config — the protocol itself must not be duplicated there.

The discipline the text encodes:

1. do not state project history, past decisions, people, facts, or prior work from memory alone
2. use `search` for prior discussions, decisions, and text evidence
3. use `kg_query` for entity and relationship facts
4. if results are missing or ambiguous, say so explicitly instead of guessing
5. invalidate and replace KG facts when reality changes

## Errors

The JSON-RPC boundary catches `CastleError` and returns tool-level error payloads. Unexpected exceptions become generic internal errors.

## When to use the CLI instead

Use the normal CLI if you want to:
- ingest files (`gather`)
- inspect status (`survey`)
- run sync (`serve`, `sync`)

Use MCP when you want an assistant to call those memory read/write operations directly during a conversation.
