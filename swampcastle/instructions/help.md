# SwampCastle

AI memory system. Store everything, find anything. Local, free, no API key.

---

## Slash Commands

| Command              | Description                    |
|----------------------|--------------------------------|
| /swampcastle:init      | Install and set up SwampCastle   |
| /swampcastle:search    | Search your memories           |
| /swampcastle:mine      | Mine projects and conversations|
| /swampcastle:status    | Palace overview and stats      |
| /swampcastle:help      | This help message              |

---

## MCP Tools (19)

### Palace (read)
- swampcastle_status -- Palace status and stats
- swampcastle_list_wings -- List all wings
- swampcastle_list_rooms -- List rooms in a wing
- swampcastle_get_taxonomy -- Get the full taxonomy tree
- swampcastle_search -- Search memories by query
- swampcastle_check_duplicate -- Check if a memory already exists
- swampcastle_get_aaak_spec -- Get the AAAK specification

### Palace (write)
- swampcastle_add_drawer -- Add a new memory (drawer)
- swampcastle_delete_drawer -- Delete a memory (drawer)

### Knowledge Graph
- swampcastle_kg_query -- Query the knowledge graph
- swampcastle_kg_add -- Add a knowledge graph entry
- swampcastle_kg_invalidate -- Invalidate a knowledge graph entry
- swampcastle_kg_timeline -- View knowledge graph timeline
- swampcastle_kg_stats -- Knowledge graph statistics

### Navigation
- swampcastle_traverse -- Traverse the palace structure
- swampcastle_find_tunnels -- Find cross-wing connections
- swampcastle_graph_stats -- Graph connectivity statistics

### Agent Diary
- swampcastle_diary_write -- Write a diary entry
- swampcastle_diary_read -- Read diary entries

---

## CLI Commands

    swampcastle init <dir>                  Initialize a new palace
    swampcastle mine <dir>                  Mine a project (default mode)
    swampcastle mine <dir> --mode convos    Mine conversation exports
    swampcastle search "query"              Search your memories
    swampcastle split <dir>                 Split large transcript files
    swampcastle wake-up                     Load palace into context
    swampcastle compress                    Compress palace storage
    swampcastle status                      Show palace status
    swampcastle repair                      Rebuild vector index
    swampcastle mcp                         Show MCP setup command
    swampcastle hook run                    Run hook logic (for harness integration)
    swampcastle instructions <name>         Output skill instructions

---

## Auto-Save Hooks

- Stop hook -- Automatically saves memories every 15 messages. Counts human
  messages in the session transcript (skipping command-messages). When the
  threshold is reached, blocks the AI with a save instruction. Uses
  ~/.swampcastle/hook_state/ to track save points per session. If
  stop_hook_active is true, passes through to prevent infinite loops.

- PreCompact hook -- Emergency save before context compaction. Always blocks
  with a comprehensive save instruction because compaction means the AI is
  about to lose detailed context.

Hooks read JSON from stdin and output JSON to stdout. They can be invoked via:

    echo '{"session_id":"abc","stop_hook_active":false,"transcript_path":"..."}' | swampcastle hook run --hook stop --harness claude-code

---

## Architecture

    Wings (projects/people)
      +-- Rooms (topics)
            +-- Closets (summaries)
                  +-- Drawers (verbatim memories)

    Halls connect rooms within a wing.
    Tunnels connect rooms across wings.

The palace is stored locally using ChromaDB for vector search and SQLite for
metadata. No cloud services or API keys required.

---

## Getting Started

1. /swampcastle:init -- Set up your palace
2. /swampcastle:mine -- Mine a project or conversation
3. /swampcastle:search -- Find what you stored
