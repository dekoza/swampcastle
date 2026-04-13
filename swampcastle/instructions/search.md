# SwampCastle Search

When the user wants to find stored memory:

## 1. Extract the core query

Identify:
- the semantic query
- optional wing filter
- optional room filter

## 2. Prefer MCP when available

Use these tools in roughly this order:
- `swampcastle_search`
- `swampcastle_list_wings`
- `swampcastle_list_rooms`
- `swampcastle_get_taxonomy`
- `swampcastle_traverse`
- `swampcastle_find_tunnels`

## 3. CLI fallback

```bash
swampcastle seek "query" [--wing X] [--room Y] [--results N]
```

Alias:

```bash
swampcastle search "query"
```

## 4. Present results clearly

Include:
- wing
- room
- similarity
- short quoted excerpt

## 5. Offer next steps

Useful follow-ups:
- narrow to a wing or room
- inspect taxonomy
- traverse related rooms
- check tunnels across wings
