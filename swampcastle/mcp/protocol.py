"""The SwampCastle protocol text, served as MCP server instructions.

Primary delivery is the `instructions` field of the `initialize` result —
clients put it in the model's context automatically. The `status` digest
carries only a short gist; `swampcastle herald` prints this text as the
CLI fallback for hook-less clients. Tool names are written bare: each
client applies its own prefix (Claude Code: `mcp__swampcastle__status`),
so the text never hardcodes one.
"""

SERVER_INSTRUCTIONS = """SwampCastle protocol

SwampCastle is this user's persistent memory. Call status first, before any task work — it returns the session digest (project memory, castle totals, staleness).

Core discipline

1. Never state project history, past decisions, people, or prior work from memory alone. Query first; if results are missing or ambiguous, say so — do not guess.
2. Scope queries with wing/room filters when the project context is known. Run get_taxonomy if you don't know the castle's structure yet.

Reading

| Purpose | Tool | Notes |
|---|---|---|
| Session digest | status | Call first; pass project_dir to scope |
| Prior discussions, decisions, context | search | query = short keywords, not sentences |
| Entity facts and relationships | kg_query | By entity name; as_of for point-in-time |
| Fact timeline | kg_timeline | Chronological entity history |
| KG overview | kg_stats | Entities, triples, relationship types |
| Castle structure | get_taxonomy | Wing → room → drawer-count tree |
| Wings / rooms | list_wings, list_rooms | Drawer counts |
| Graph traversal | traverse, find_tunnels | Walk rooms, cross-wing bridges |
| Graph stats | graph_stats | Connectivity overview |
| Source origins | get_origin | Manifest by origin_id or source_file |
| Curation data | get_curation | Local audit-overlay curation |
| Catalog cards | list_catalog_cards | Derived catalog for a wing |
| Diary entries | diary_read | Agent's recent diary entries |
| Typed records | record_get | By ID, kind filter, or with tombstones |
| GC status | record_gc_status | Record IDs pending garbage collection |
| AAAK dialect | get_aaak_spec | Compressed format used in stored text |

Writing

Read before you write; persist what future sessions will need. Save when the session produced: a user correction; a command or fix that worked; a debugging insight; a decision and its rationale; a stated preference; a durable fact about a project or person.

| Tool | What to store |
|---|---|
| checkpoint | End-of-session save in one call: items (drawers) + one diary entry, deduped |
| add_drawer | Single targeted write of long-form content: a decision, discussion, spec |
| delete_drawer | Remove a drawer by ID |
| kg_add | Structured facts (subject → predicate → object) |
| kg_invalidate | Mark a fact as no longer true |
| diary_write | A lone session note when there is nothing else to file |
| record_add | Typed canonical records |

At session end, file the session with one checkpoint call instead of many separate check_duplicate/add_drawer/diary_write calls.

Before writing:
- Duplicates: call check_duplicate before add_drawer (checkpoint dedups internally).
- Stale facts: call kg_invalidate before adding the replacement via kg_add.
- Logical deletion: record_tombstone (grace period applies); permanent: record_gc_collect after the grace period.

Tool names are bare here; your client may prefix them (e.g. mcp__swampcastle__status)."""
