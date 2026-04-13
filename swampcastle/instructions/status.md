# SwampCastle Status

Show the current state of the castle.

## 1. Prefer MCP

If MCP is available, use:
- `swampcastle_status`
- optionally `swampcastle_kg_stats`
- optionally `swampcastle_graph_stats`

## 2. CLI fallback

```bash
swampcastle survey
```

Alias:

```bash
swampcastle status
```

## 3. Summarize briefly

Report:
- total drawers
- number of wings
- number of rooms
- optionally KG / graph stats when available

## 4. Suggest the next action

Examples:
- empty castle → suggest `swampcastle gather <dir>`
- populated castle → suggest `swampcastle seek "query"`
