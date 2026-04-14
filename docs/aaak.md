# AAAK dialect

AAAK is an experimental compact writing format used for dense memory summaries.

It is **not** the default storage format in v4. Raw verbatim drawers remain the primary retrieval path.

## What AAAK is good for

- compact diary entries
- dense session summaries
- human / model-readable shorthand

## What AAAK is not

- not lossless compression
- not the main retrieval representation
- not currently a finished end-to-end CLI storage pipeline

## Status

The benchmark headline for SwampCastle comes from raw verbatim storage, not AAAK mode.

AAAK remains useful as a deliberate summarization layer, but you should treat it as optional and experimental.

## Python API

```python
from swampcastle.dialect import Dialect

dialect = Dialect()
compressed = dialect.compress("Alice and Jordan discussed the auth migration with Kai")
stats = dialect.compression_stats("Alice and Jordan discussed the auth migration with Kai", compressed)
```

You can also load entity configuration from JSON:

```python
dialect = Dialect.from_config("entities.json")
```

## CLI

```bash
# Preview only (default)
swampcastle distill
swampcastle compress

# Persist AAAK metadata explicitly
swampcastle distill --apply
swampcastle compress --apply

# Force preview mode explicitly
swampcastle distill --dry-run
```

Honest status: the current CLI command is preview-oriented by default. It does
not yet implement a full persistent compressed-store workflow, and `--apply`
only stores AAAK in metadata — it does not replace verbatim drawer content.

## MCP

The AAAK spec is returned by:
- `swampcastle_status`
- `swampcastle_get_aaak_spec`

## Typical structure

AAAK commonly uses:
- short entity codes
- explicit flags
- compressed relationship notation
- compact date / importance markers

Example:

```text
SESSION:2026-04-04|KAI+ALC|auth.switch.confirmed|DECISION|★★★
```

## Recommendation

Use AAAK when you are deliberately summarizing. Use raw drawers when you care about retrieval quality.
