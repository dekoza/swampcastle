# Searching

## CLI

Primary command:

```bash
swampcastle seek "auth migration"
```

Alias:

```bash
swampcastle search "auth migration"
```

Filters:

```bash
swampcastle seek "billing retries" --wing myapp
swampcastle seek "token rotation" --wing myapp --room auth
swampcastle seek "recent auth work" --contributor dekoza
swampcastle seek "postgres" --results 10
```

The CLI prints verbatim text plus wing / room / similarity, and includes contributor when present.

## Python API

Recommended path: `Castle` + `SearchQuery`.

```python
from swampcastle.castle import Castle
from swampcastle.models import SearchQuery
from swampcastle.settings import CastleSettings
from swampcastle.storage import factory_from_settings

settings = CastleSettings(_env_file=None)
factory = factory_from_settings(settings)

with Castle(settings, factory) as castle:
    result = castle.search.search(
        SearchQuery(
            query="auth migration",
            wing="myapp",
            room="auth",
            contributor="dekoza",
            limit=5,
        )
    )

for hit in result.results:
    print(hit.wing, hit.room, hit.contributor, hit.similarity, hit.text[:120])
```

## Duplicate checks

The same service also exposes duplicate detection:

```python
from swampcastle.models import DuplicateCheckQuery

result = castle.search.check_duplicate(
    DuplicateCheckQuery(content="We switched auth providers because rotation got simpler.")
)
```

MCP exposes the same flow through `swampcastle_check_duplicate`.

## Query model

`SearchQuery` fields:

| Field | Type | Default |
|---|---|---|
| `query` | `str` | required |
| `limit` | `int` | `5` |
| `wing` | `str \| None` | `None` |
| `room` | `str \| None` | `None` |
| `contributor` | `str \| None` | `None` |
| `context` | `str \| None` | `None` |
| `lexical_rerank` | `bool` | `False` |

`context` is background context for callers. The search embedding is built from
`query`, not from the extra context. When `lexical_rerank=true`, `context` is
used only in the reranking pass over dense candidates; it is **not** embedded.

`lexical_rerank=true` widens dense candidate retrieval and then reranks those
candidates by lexical overlap with `query` (+ optional `context`). This is a
lightweight first step toward hybrid retrieval; it is not a full sparse index.

## Sanitization

`SearchService` sanitizes the query through `query_sanitizer.py` before it hits the embedder. This matters for MCP callers because LLMs sometimes accidentally paste system-prompt junk into a search request.

If sanitization changes the query, the response includes:
- `query_sanitized = true`
- a `sanitizer` metadata object

## How ranking works

At a high level:

1. the query is embedded
2. the collection backend searches nearest neighbors
3. optional `wing` / `room` / `contributor` filters narrow the candidate set
4. results are returned as `SearchHit` models

The concrete ANN implementation depends on the active backend:
- LanceDB in local mode
- pgvector in PostgreSQL mode
- substring-scored in-memory search for tests

## Castle status vs search

`swampcastle survey` / `swampcastle_status` answers:
- how much memory is stored
- which wings and rooms exist

`swampcastle seek` / `swampcastle_search` answers:
- where a specific fact or decision appears
- which stored chunks are closest to a query

Use both. Status tells you the shape of the castle; search tells you what is inside it.
