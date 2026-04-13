# Mining

SwampCastle ingests two kinds of material:

- **project files**
- **conversation exports**

In both cases the output is verbatim drawer content stored through the active `CollectionStore` backend.

## Project files

```bash
swampcastle gather ~/projects/myapp
```

Alias:

```bash
swampcastle mine ~/projects/myapp
```

### What it does

- walks the directory tree
- skips common junk directories (`.git`, `.venv`, `node_modules`, caches, build outputs)
- respects `.gitignore` by default
- chunks readable text files into drawers
- assigns a wing and room to each chunk
- skips already-mined files when possible

### Common options

```bash
swampcastle gather <dir> \
  [--wing NAME] \
  [--no-gitignore] \
  [--include-ignored PATH] \
  [--agent NAME] \
  [--limit N] \
  [--dry-run]
```

Examples:

```bash
swampcastle gather ~/projects/myapp --wing myapp
swampcastle gather ~/projects/myapp --include-ignored docs/generated
swampcastle gather ~/projects/myapp --dry-run --limit 25
```

## Conversation exports

```bash
swampcastle gather ~/exports --mode convos --wing myapp
```

### Supported sources

The normalizer recognizes common transcript formats such as:
- Claude Code JSONL
- Claude export JSON
- ChatGPT export JSON
- Slack export JSON
- Codex-style JSONL
- plain text transcripts

### Extraction modes

Default exchange-pair chunking:

```bash
swampcastle gather ~/exports --mode convos --extract exchange
```

General extraction:

```bash
swampcastle gather ~/exports --mode convos --extract general
```

`general` classifies chunks into broader memory types instead of keeping only exchange-pair structure.

## Room detection

`swampcastle build` / `swampcastle init` is the preview step for room and entity detection:

```bash
swampcastle build ~/projects/myapp
```

That command helps you inspect the inferred structure before you ingest anything.

## Splitting mega-files

Some transcript dumps contain multiple sessions in one file.

```bash
swampcastle cleave ~/exports
swampcastle cleave ~/exports --dry-run
swampcastle cleave ~/exports --output-dir ~/split-exports
```

Alias: `swampcastle split`

## Duplicate handling

There are three distinct duplicate controls:

1. file-level skipping during project mining
2. file-level skipping during conversation mining
3. semantic duplicate checks through `SearchService`

For bulk cleanup of already-stored drawers, use the backend-agnostic dedup utility:

```bash
python -m swampcastle.dedup --dry-run
python -m swampcastle.dedup --threshold 0.10
```

There is no dedicated top-level `swampcastle dedup` CLI subcommand yet.

## Backend behavior

Mining now routes through the configured storage factory.

That means the same ingest code can target:
- local LanceDB + SQLite
- PostgreSQL + pgvector
- in-memory stores in tests

You can also inject a `storage_factory=` programmatically when calling `mine()` or `mine_convos()` from Python.
