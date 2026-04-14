# Knowledge graph

SwampCastle keeps structured facts in a graph store separate from drawer search.

## Backends

- **Local mode:** `SQLiteGraph`
- **PostgreSQL mode:** `PostgresGraphStore`

The high-level API is the same either way because `Castle.graph` sits on top of the `GraphStore` contract.

## Recommended API: Castle.graph

```python
from swampcastle.castle import Castle
from swampcastle.settings import CastleSettings
from swampcastle.storage import factory_from_settings

settings = CastleSettings(_env_file=None)
factory = factory_from_settings(settings)

with Castle(settings, factory) as castle:
    castle.graph.kg_add(subject="Kai", predicate="works_on", obj="Orion")
    facts = castle.graph.kg_query(entity="Kai")
    print(facts.facts)
```

### Available high-level operations

- `kg_add(subject, predicate, obj, valid_from=None, source_closet=None)`
- `kg_query(entity, as_of=None, direction="both")`
- `kg_invalidate(subject, predicate, obj, ended=None)`
- `kg_timeline(entity=None)`
- `kg_stats()`
- `traverse(start_room, max_hops=2)`
- `find_tunnels(wing_a=None, wing_b=None)`
- `graph_stats()`

## Direct low-level stores

### SQLiteGraph

```python
from swampcastle.storage.sqlite_graph import SQLiteGraph

graph = SQLiteGraph("/tmp/knowledge_graph.sqlite3")
graph.add_triple(subject="Kai", predicate="works_on", obj="Orion")
```

### PostgresGraphStore

Open it through `PostgresStorageFactory` rather than constructing it by hand unless you already own the pool.

## Graph model

Facts are stored as triples:

```text
subject → predicate → object
```

Example:

```text
Kai → works_on → Orion
```

Optional temporal fields:
- `valid_from`
- `valid_to`

That lets you ask both:
- what is true now?
- what was true at a past date?

## Duplicate handling

Adding the exact same active fact twice does not create a second live triple. The stores check for an existing active triple with the same `subject + predicate + object`.

## Time filtering

`as_of` keeps only facts valid at that moment:

- `valid_from` is `NULL` or `<= as_of`
- `valid_to` is `NULL` or `>= as_of`

## Candidate-triple proposals (proposal-first workflow)

SwampCastle now supports a separate proposal layer for extracted facts.

These are **not** part of the accepted KG until you review and accept them.

### Candidate proposal service

`Castle` exposes:

- `castle.kg_proposals.propose(candidate)`
- `castle.kg_proposals.list_proposals(filter_params=None)`
- `castle.kg_proposals.get_proposal(candidate_id)`
- `castle.kg_proposals.accept(cmd)`
- `castle.kg_proposals.reject(candidate_id)`
- `castle.kg_proposals.extract_from_drawers(...)`

Accepted proposals can optionally invalidate conflicting current facts for a
small exclusive predicate set (`uses`, `migrated_to`, `deployed_to`, etc.) via
`CandidateReviewCommand(action="accept_and_invalidate_conflict")` or the CLI
flag `--invalidate-conflicts`.

Acceptance can also override the extracted subject / predicate / object before
writing into the canonical KG. This is the v1 "edit-before-accept" workflow.

### Conflict markers

`list_proposals()` annotates proposals with `conflicts_with` when the proposed
fact disagrees with a currently-active fact for an exclusive predicate.
This is advisory review metadata — the proposal is still just a proposal until
accepted.

The CLI can surface only those proposals via:

```bash
swampcastle kg review --conflicts-only
```

### Why proposals are separate

Extracted facts are guesses until reviewed. The accepted KG remains the source
of truth; proposals are stored separately so bad extraction does not poison
normal KG queries.

### Storage status

- **SQLiteGraph:** candidate proposal storage implemented
- **InMemoryGraphStore:** candidate proposal storage implemented
- **PostgresGraphStore:** candidate proposal storage not implemented yet
  (raises `NotImplementedError` for the MVP)

## MCP tools

The graph is available through:

- `swampcastle_kg_query`
- `swampcastle_kg_add`
- `swampcastle_kg_invalidate`
- `swampcastle_kg_timeline`
- `swampcastle_kg_stats`
- `swampcastle_traverse`
- `swampcastle_find_tunnels`
- `swampcastle_graph_stats`

## Local SQLite schema

The local graph store uses two tables:
- `entities`
- `triples`

See [`docs/schema.sql`](schema.sql) for a current SQLite schema snapshot.
