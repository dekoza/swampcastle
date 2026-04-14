# MCP server

SwampCastle exposes 19 tools over JSON-RPC stdin/stdout.

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
5. serves JSON-RPC over stdin/stdout

## Tool catalog

### Catalog / status
- `swampcastle_status`
- `swampcastle_list_wings`
- `swampcastle_list_rooms`
- `swampcastle_get_taxonomy`
- `swampcastle_get_aaak_spec`

### Search
- `swampcastle_search`
- `swampcastle_check_duplicate`

### Drawer writes
- `swampcastle_add_drawer`
- `swampcastle_delete_drawer`

### Knowledge graph
- `swampcastle_kg_query`
- `swampcastle_kg_add`
- `swampcastle_kg_invalidate`
- `swampcastle_kg_timeline`
- `swampcastle_kg_stats`

### Castle graph navigation
- `swampcastle_traverse`
- `swampcastle_find_tunnels`
- `swampcastle_graph_stats`

### Agent diary
- `swampcastle_diary_write`
- `swampcastle_diary_read`

## Important request shapes

### search

`swampcastle_search` uses the `SearchQuery` model:

| Field | Type | Required |
|---|---|---|
| `query` | string | yes |
| `limit` | integer | no |
| `wing` | string | no |
| `room` | string | no |
| `contributor` | string | no |
| `context` | string | no |
| `lexical_rerank` | boolean | no |

### add drawer

`swampcastle_add_drawer` uses `AddDrawerCommand`:

| Field | Type | Required |
|---|---|---|
| `wing` | string | yes |
| `room` | string | yes |
| `content` | string | yes |
| `source_file` | string | no |
| `added_by` | string | no |

### graph query

`swampcastle_kg_query` uses `KGQueryParams`:

| Field | Type | Required |
|---|---|---|
| `entity` | string | yes |
| `as_of` | string | no |
| `direction` | `outgoing \| incoming \| both` | no |

## Protocol expectations

`swampcastle_status` returns a strict memory-use protocol and AAAK spec. The intended usage is:

1. do not state project history, past decisions, people, facts, or prior work from memory alone
2. use `swampcastle_search` for prior discussions, decisions, and text evidence
3. use `swampcastle_kg_query` for entity and relationship facts
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
