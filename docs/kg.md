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
