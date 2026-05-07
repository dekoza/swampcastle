# Mining adapters

SwampCastle now has an **internal source-adapter seam** for ingest.

This is not a public plugin API yet.
It exists to stop project-file ingest and conversation ingest from drifting into two unrelated code paths.

## Scope

Current adapters live under:

```text
swampcastle/mining/adapters/
```

Current shipped adapters:
- `ProjectFilesAdapter`
- `ConversationExportsAdapter`

These adapters are used internally by:
- `swampcastle.mining.miner.mine()`
- `swampcastle.mining.convo.mine_convos()`

The public CLI does **not** change:
- `swampcastle gather ...`
- `swampcastle mine ...`

still remain the supported entry points.

## Current contract

The internal base contract lives in:

```text
swampcastle/mining/adapters/base.py
```

Current shape:

```python
class BaseSourceAdapter(ABC):
    name: str
    declared_transformations: tuple[str, ...] = ()

    @abstractmethod
    def scan(self, *, limit: int = 0) -> list[SourceItem]:
        ...

    @abstractmethod
    def ingest(self, item: SourceItem, **kwargs):
        ...
```

The contract is intentionally small:
- `scan()` discovers ingestable items
- `ingest()` prepares or executes per-item ingest work
- `declared_transformations` makes non-verbatim shaping visible in code

## Current adapters

## 1. `ProjectFilesAdapter`

Purpose:
- project-file discovery and per-file ingest routing

Current behavior:
- delegates file discovery to the existing project scanner
- delegates per-file ingest to the existing project mining logic
- keeps project-file declared transformations empty

Current declaration:

```python
name = "project_files"
declared_transformations = ()
```

That means project-file ingest remains the baseline verbatim path. It reads text and chunks it, but it does not advertise a transcript-normalization transform the way conversation ingest does.

## 2. `ConversationExportsAdapter`

Purpose:
- conversation-export discovery and per-transcript ingest preparation

Current behavior:
- delegates file discovery to the conversation scanner
- delegates transcript analysis to the existing conversation mining helpers
- exposes transcript normalization as declared transformations

Current declaration:

```python
name = "conversation_exports"
declared_transformations = (
    "jsonl_normalize",
    "json_normalize",
)
```

That is deliberate. Conversation ingest is not byte-preserving in the same sense as project-file ingest. It normalizes several export shapes into a shared transcript form before chunking.

## Why this is internal-only for now

Do not confuse this seam with a stable plugin API. It is not one.

Reasons:
- no compatibility promise yet
- no third-party packaging contract yet
- no schema/version policy for external adapters yet
- no dedicated MCP surface yet

The current goal is simpler:
- keep project and conversation ingest aligned
- make transformation declarations explicit
- make future adapter growth less chaotic

## What this changes architecturally

Before this seam:
- project ingest and conversation ingest were just two growing modules
- reuse depended on discipline
- transformation declarations were implicit

After this seam:
- ingest source discovery is routed through adapter objects
- declared transforms are visible in code and tests
- future source types have an obvious internal landing zone

## What this does **not** change

- no public plugin marketplace
- no user-facing adapter selection flags
- no external contract for third-party packages
- no sync behavior changes
- no MCP tool changes

## Current test coverage

The adapter seam is pinned by tests that verify:
- declared transformation tuples are visible
- adapter `scan()` matches current direct scanner behavior
- `mine()` uses `ProjectFilesAdapter` in the sequential path
- `mine_convos()` uses `ConversationExportsAdapter`

That keeps this refactor honest: the seam is real, not just documentation.

## Future direction

If SwampCastle later grows more source types, they should land here first as **internal adapters**.
Only after that stabilizes should a public plugin contract even be considered.
