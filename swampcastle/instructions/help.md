# SwampCastle

Local memory for AI assistants.

## Recommended flow

1. `swampcastle build <dir>` — preview rooms and entity candidates
2. `swampcastle gather <dir>` — ingest project files or conversation exports
3. `swampcastle seek "query"` — search stored memory
4. `swampcastle survey` — inspect current wings / rooms / drawer counts
5. `swampcastle drawbridge` — print MCP setup command

## MCP tools

Catalog / status:
- `swampcastle_status`
- `swampcastle_list_wings`
- `swampcastle_list_rooms`
- `swampcastle_get_taxonomy`
- `swampcastle_get_aaak_spec`

Search:
- `swampcastle_search`
- `swampcastle_check_duplicate`

Drawer writes:
- `swampcastle_add_drawer`
- `swampcastle_delete_drawer`

Knowledge graph:
- `swampcastle_kg_query`
- `swampcastle_kg_add`
- `swampcastle_kg_invalidate`
- `swampcastle_kg_timeline`
- `swampcastle_kg_stats`

Navigation:
- `swampcastle_traverse`
- `swampcastle_find_tunnels`
- `swampcastle_graph_stats`

Agent diary:
- `swampcastle_diary_write`
- `swampcastle_diary_read`

## CLI commands

User-facing commands:

```text
swampcastle build <dir>
swampcastle gather <dir>
swampcastle seek "query"
swampcastle survey
swampcastle drawbridge
swampcastle drawbridge run
swampcastle cleave <dir>
swampcastle serve --host 0.0.0.0 --port 7433
swampcastle sync --server http://host:7433
```

Compatibility aliases still exist:
- `init` → `build`
- `mine` → `gather`
- `search` → `seek`
- `status` → `survey`
- `mcp` → `drawbridge`
- `split` → `cleave`

## Architecture summary

```text
Castle
  ├── CatalogService
  ├── SearchService
  ├── VaultService
  └── GraphService
        ↓
CollectionStore + GraphStore
```

Default local storage is LanceDB + SQLite.
Optional server storage is PostgreSQL + pgvector.
