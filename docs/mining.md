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
- tags chunks with a best-effort `contributor` when the project config includes a `team` list
- skips already-mined files when possible

### Common options

```bash
swampcastle gather <dir> \
  [--wing NAME] \
  [--no-gitignore] \
  [--include-ignored PATH] \
  [--agent NAME] \
  [--limit N] \
  [--dry-run] \
  [--extract-kg-proposals]
```

Contributor tagging does not come from a `gather` flag. It comes from `.swampcastle.yaml`:

```yaml
wing: myapp
team:
  - dekoza
  - sarah
rooms:
  - name: backend
    description: Backend code
```

Examples:

```bash
swampcastle gather ~/projects/myapp --wing myapp
swampcastle gather ~/projects/myapp --include-ignored docs/generated
swampcastle gather ~/projects/myapp --dry-run --limit 25
swampcastle gather ~/projects/myapp --extract-kg-proposals
```

## Optional KG proposal extraction during ingest

If you pass `--extract-kg-proposals`, SwampCastle will run the rule-based KG
extractor after ingest finishes and store the output in the **proposal store**.

Important constraints:

- this is **proposal-only** extraction
- it does **not** write accepted KG facts
- it is opt-in
- it is skipped during `--dry-run`
- repeated runs are idempotent because proposal IDs are deterministic

This is a convenience integration for teams that want proposal extraction to
follow ingest automatically. Review and acceptance still happen separately via:

```bash
swampcastle kg review
swampcastle kg accept <candidate-id>
swampcastle kg reject <candidate-id>
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

Conversation ingest also performs contributor tagging when the source directory has `.swampcastle.yaml` with a `team` list and the files live inside a git repository.

## Project setup

`swampcastle project` prepares a directory for mining by writing `.swampcastle.yaml`:

```bash
swampcastle project ~/projects/myapp --team dekoza sarah
```

That command helps you inspect and save the inferred structure before you ingest anything. New setups use `.swampcastle.yaml`; if a legacy `swampcastle.yaml` exists, SwampCastle migrates it automatically.

The optional `team` list is shared project metadata. During ingest, SwampCastle checks git history for each file, matches the author against the configured team, and stores the matched identifier in drawer metadata as `contributor`.

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
