# SwampCastle Mine

When the user wants to ingest data, guide them through these choices.

## 1. Ask what they want to ingest

Clarify whether the source is:
- a project directory
- conversation exports
- a mixed folder that should be handled as conversations

## 2. Choose the command

### Project files

```bash
swampcastle gather <dir>
```

If they want contributor tagging, make sure the project has `.swampcastle.yaml` with a `team` list, usually created via:

```bash
swampcastle project <dir> --team dekoza sarah
```

### Conversation exports

```bash
swampcastle gather <dir> --mode convos
```

### General extraction

```bash
swampcastle gather <dir> --mode convos --extract general
```

## 3. Optional helpers

### Preview only

```bash
swampcastle gather <dir> --dry-run
```

### Force a wing

```bash
swampcastle gather <dir> --wing <name>
```

### Split mega-files first

```bash
swampcastle cleave <dir> --dry-run
```

## 4. After ingest

Recommend:
- `swampcastle seek "query"`
- `swampcastle seek "query" --contributor dekoza`
- `swampcastle survey`
- additional ingest from more sources
