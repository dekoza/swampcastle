<div align="center">

<img src="assets/Swamp.webp" alt="SwampCastle" width="420">

# SwampCastle

Built on ruins of [MemPalace](https://github.com/MemPalace/mempalace). And since MemPalace's first public version was v3, it clearly indicates that v1 and v2 sank. That base v3 was burned down, dismantled, and than sank.

**The fourth one stayed up.**

Persistent, searchable memory for AI assistants. Local. Free. No API key.

[![][version-shield]][release-link]
[![][python-shield]][python-link]
[![][license-shield]][license-link]

</div>

---

> **⚠ Important:** Fake SwampCastle websites are distributing malware. Strange websites lying in swamps distributing binaries is no basis for a memory system. The first three castles sank — don't download the rubble. The only legitimate sources are [GitHub](https://github.com/dekoza/swampcastle) and [PyPI](https://pypi.org/project/swampcastle/). See also [launch week errata](NOTICES.md).

---

## What SwampCastle does

SwampCastle stores your AI conversations and project files in a local vector database (LanceDB), organized into a navigable structure of **wings** (projects/people), **rooms** (topics), and **drawers** (verbatim text). A companion **knowledge graph** (SQLite) tracks entity relationships with temporal validity.

Your AI assistant connects via [MCP](docs/mcp.md) and gets persistent memory across sessions — it can search past conversations, recall decisions, and track how facts change over time. Everything runs locally. Multi-device sync keeps your palace consistent across machines.

**96.6% R@5 on [LongMemEval](benchmarks/BENCHMARKS.md)** in raw verbatim mode, zero API calls.

## Install

```bash
pip install swampcastle
```

Requires Python 3.9+. Core dependencies: `lancedb`, `onnxruntime`, `tokenizers`, `pyyaml`. No internet needed after install (except for first-run ONNX model download, ~87 MB, cached).

Optional extras:

```bash
pip install swampcastle[chroma]     # legacy ChromaDB backend (for migration)
pip install swampcastle[gpu]        # GPU-accelerated embeddings via sentence-transformers
pip install swampcastle[server]     # sync server (FastAPI + uvicorn)
```

## Quick start

```bash
# 1. Detect rooms from your project structure
swampcastle init ~/projects/myapp

# 2. Mine project files into the palace
swampcastle mine ~/projects/myapp

# 3. Mine conversation exports (Claude, ChatGPT, Slack, Codex)
swampcastle mine ~/chats/ --mode convos

# 4. Search
swampcastle search "why did we switch to GraphQL"
```

Then connect your AI assistant:

```bash
# Claude Code
claude mcp add swampcastle -- python -m swampcastle.drawbridge

# Gemini CLI
gemini mcp add swampcastle python -m swampcastle.drawbridge --scope user
```

Now ask your AI anything about your past work — it searches the palace automatically.

→ Full walkthrough: [docs/getting-started.md](docs/getting-started.md)

## Multi-device sync

Keep your palace synchronized across machines with a hub-and-spoke sync model.

```bash
# On your home server (the hub)
pip install swampcastle[server]
swampcastle serve --host 0.0.0.0 --port 7433

# On any device (spoke)
swampcastle sync --server http://homeserver:7433
```

Sync uses version vectors and last-writer-wins conflict resolution. All communication is plain HTTP — no cloud services involved.

→ Sync guide: [docs/sync.md](docs/sync.md)

## How the palace is organized

SwampCastle uses a spatial metaphor to organize memories. This isn't cosmetic — the structure drives metadata filtering that improves retrieval accuracy.

```
WING (project or person)
  └── ROOM (topic: auth, billing, deploy, ...)
        └── DRAWER (verbatim text chunk)
```

- **Wings** — one per project, person, or domain.
- **Rooms** — specific topics within a wing.
- **Tunnels** — when the same room appears in multiple wings, a tunnel connects them.
- **Halls** — memory type corridors: `hall_facts`, `hall_events`, `hall_discoveries`, `hall_preferences`, `hall_advice`.
- **Drawers** — the actual verbatim text. Never summarized.

Filtering by wing + room yields up to +34% retrieval improvement over unfiltered search (measured on 22,000+ real memories).

→ Architecture details: [docs/architecture.md](docs/architecture.md)

## MCP server

19 tools via [MCP](https://modelcontextprotocol.io/). Once connected, your AI reads, writes, and searches the palace without manual commands.

**Read:** `swampcastle_status`, `swampcastle_search`, `swampcastle_list_wings`, `swampcastle_list_rooms`, `swampcastle_get_taxonomy`, `swampcastle_check_duplicate`, `swampcastle_get_aaak_spec`

**Write:** `swampcastle_add_drawer`, `swampcastle_delete_drawer`

**Knowledge graph:** `swampcastle_kg_query`, `swampcastle_kg_add`, `swampcastle_kg_invalidate`, `swampcastle_kg_timeline`, `swampcastle_kg_stats`

**Navigation:** `swampcastle_traverse`, `swampcastle_find_tunnels`, `swampcastle_graph_stats`

**Agent diary:** `swampcastle_diary_write`, `swampcastle_diary_read`

→ Full tool reference: [docs/mcp.md](docs/mcp.md)

## Knowledge graph

Temporal entity-relationship triples in SQLite. Track facts that change over time.

```python
from swampcastle.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()
kg.add_triple("Kai", "works_on", "Orion", valid_from="2025-06-01")

kg.query_entity("Kai")                          # what's true now
kg.query_entity("Maya", as_of="2026-01-20")     # what was true then
kg.invalidate("Kai", "works_on", "Orion", ended="2026-03-01")
```

→ Full API and schema: [docs/kg.md](docs/kg.md)

## Mining

Two ingest modes, six input formats.

**Project mining** scans directories for code, docs, and notes. Chunks by paragraph, respects `.gitignore`.

**Conversation mining** parses chat exports (Claude Code JSONL, Claude.ai JSON, ChatGPT JSON, Slack JSON, Codex CLI JSONL, plain text). Chunks by exchange pair.

```bash
swampcastle mine ~/projects/myapp                              # project files
swampcastle mine ~/chats/ --mode convos --wing myapp           # conversations
swampcastle mine ~/chats/ --mode convos --extract general      # auto-classify into 5 memory types
swampcastle split ~/chats/                                     # split mega-files first
```

→ Mining guide: [docs/mining.md](docs/mining.md)

## Benchmarks

| Benchmark | Mode | Score | API Calls |
|-----------|------|-------|-----------|
| LongMemEval R@5 | Raw (LanceDB) | **96.6%** | Zero |
| LongMemEval R@5 | Hybrid + Haiku rerank | **100%** | ~500 |
| LoCoMo R@10 | Raw, session level | **60.3%** | Zero |

Runners and methodology in [benchmarks/](benchmarks/).

## Documentation

| Document | Contents |
|----------|----------|
| [Getting started](docs/getting-started.md) | Install, first palace, first search, MCP setup |
| [Architecture](docs/architecture.md) | Palace model, memory layers, data flow |
| [Mining](docs/mining.md) | Project files, conversations, formats, splitting |
| [Searching](docs/searching.md) | CLI search, programmatic API, filtering |
| [MCP server](docs/mcp.md) | Setup, all 19 tools, integration guides |
| [Knowledge graph](docs/kg.md) | Temporal triples, queries, Python API |
| [Hooks](docs/hooks.md) | Auto-save for Claude Code and Gemini CLI |
| [Configuration](docs/configuration.md) | Config files, env vars, defaults |
| [CLI reference](docs/cli.md) | Every command, every flag |
| [Python API](docs/python-api.md) | Programmatic usage |
| [AAAK dialect](docs/aaak.md) | Compression format, status, limitations |
| [Sync](docs/sync.md) | Multi-device replication, server setup |
| [Notices](NOTICES.md) | Security warnings, launch errata |

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and guidelines.

## License

MIT — see [LICENSE](LICENSE).

<!-- Link Definitions -->
[version-shield]: https://img.shields.io/badge/version-4.0.0-4dc9f6?style=flat-square&labelColor=0a0e14
[release-link]: https://github.com/dekoza/swampcastle/releases
[python-shield]: https://img.shields.io/badge/python-3.9+-7dd8f8?style=flat-square&labelColor=0a0e14&logo=python&logoColor=7dd8f8
[python-link]: https://www.python.org/
[license-shield]: https://img.shields.io/badge/license-MIT-b0e8ff?style=flat-square&labelColor=0a0e14
[license-link]: https://github.com/dekoza/swampcastle/blob/main/LICENSE
