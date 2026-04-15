# Changelog

All notable changes to SwampCastle are documented in this file.

This project follows a simple versioned changelog format.

## [Unreleased]

### Changed
- MCP discovery now exposes short server tool names such as `status` and `search` instead of redundant `swampcastle_*` names.
- Legacy `swampcastle_*` MCP tool names remain callable as hidden compatibility aliases for one release and are no longer listed by discovery.

## [4.1.0] - 2026-04-15

Knowledge-graph extraction, embedder hardening, and search / indexing ergonomics release.

### Added
- Added the proposal-first knowledge graph extraction pipeline:
  - candidate-triple storage
  - `swampcastle kg extract`
  - `swampcastle kg review`
  - `swampcastle kg accept`
  - `swampcastle kg reject`
- Added conflict-aware KG review and acceptance helpers:
  - `swampcastle kg review --conflicts-only`
  - `swampcastle kg accept --invalidate-conflicts`
  - edit-before-accept support for review-time subject / predicate / object overrides
- Added optional gather-time KG proposal extraction via `swampcastle gather --extract-kg-proposals`.
- Added a labeled extractor fixture corpus and a first precision / recall regression gate for KG proposal extraction.
- Added lightweight hybrid retrieval improvements:
  - lexical reranking over dense candidates
  - backend-agnostic lexical candidate generation
- Added embedder fingerprinting and `swampcastle embedders --verify` for cross-machine verification.
- Added live progress output for `swampcastle reforge` / `swampcastle reindex`.

### Changed
- Pinned the canonical ONNX embedder path to `CPUExecutionProvider` for safer cross-machine reproducibility.
- Routed embedder configuration through `CastleSettings` and storage factories instead of relying on backend defaults.
- Hardened Lance collections to reject mixed embedder fingerprints, not only mismatched vector dimensions.
- Improved chunking to prefer paragraph / sentence / word boundaries and cleaner overlaps.
- Made `distill` / `compress` preview-first and require `--apply` for mutation.
- Added graph summary caching with invalidation on vault writes.
- Extended search with optional hybrid retrieval controls while keeping the default dense path intact.

### Fixed
- Fixed silent drawer ID collisions by hashing full content, and fixed hash-input ambiguity with separators.
- Fixed embedder cache construction races under concurrency.
- Fixed sync server and sync client support for optional bearer-token authentication.
- Fixed diary reads to avoid quadratic offset scanning behavior.
- Fixed SQLite knowledge-graph concurrency with per-thread connections and serialized writes.
- Fixed miner status reporting so large ingests are not truncated at 10k.
- Fixed query sanitization to prefer labeled-tail extraction over brittle prompt-noise handling.
- Reduced reindex progress overhead by switching to large adaptive batches instead of many tiny upserts.

### Quality gates
- Non-integration suite passing (`940 passed, 2 skipped, 5 deselected`).
- Added targeted tests for KG extraction quality, embedder reproducibility metadata, CLI review flows, reindex progress behavior, and release metadata consistency.

## [4.0.2] - 2026-04-13

CLI and configuration cleanup release.

### Added
- Added `swampcastle wizard` for global runtime configuration.
- Added automatic creation of `~/.swampcastle/config.json` on first use.
- Added dedicated project-config helpers and tests for legacy filename migration.

### Changed
- Replaced public `build` / `init` project setup with `swampcastle project <dir>`.
- Switched project-local config from `swampcastle.yaml` to `.swampcastle.yaml`.
- Made `pyproject.toml` the single source of package version truth.
- Normalized output for core CLI commands.

### Fixed
- Fixed `gather` / project setup guidance so users are pointed at the correct command.
- Removed fake sync loop flags and hardened internal command access.
- Scoped sync CLI identity data to the active castle configuration.
- Stopped `cleave` from mutating process-global `sys.argv`.

## [4.0.0] - 2026-04-13

First full SwampCastle v4 release after the MemPalace → SwampCastle rebuild.

### Added
- PostgreSQL backend support with pgvector collection storage and graph storage.
- Real legacy migration command: `swampcastle raise` / `swampcastle migrate`.
- Implemented maintenance commands:
  - `swampcastle distill`
  - `swampcastle reforge`
- Docker-based PostgreSQL integration test environment.
- Release-hardening tests for CLI commands, sync client, sync server, dialect file flows, and module entrypoint.

### Changed
- Rebranded package metadata, CLI naming, MCP tools, and documentation to SwampCastle v4.
- Rebuilt architecture around `Castle`, service boundaries, and storage factories.
- Routed sync server through storage factories instead of hardcoded Lance wiring.
- Rewrote deduplication to be backend-agnostic.
- Rewrote documentation for the v4 API, CLI, migration story, MCP server, sync model, and storage architecture.

### Fixed
- Fixed migration rollback behavior and validation for empty/corrupt legacy sources.
- Fixed metadata mutation bug in `distill()`.
- Added sync engine lifecycle cleanup.
- Restored test coverage above the project gate.
- Fixed optional FastAPI server test behavior when the `server` extra is not installed.
- Fixed SQLite graph test fixture cleanup to avoid resource leaks.

### Quality gates
- Unit tests passing.
- PostgreSQL integration tests passing.
- Coverage gate passing (`86.42%`, required `85%`).

[Unreleased]: https://github.com/dekoza/swampcastle/compare/v4.1.0...HEAD
[4.1.0]: https://github.com/dekoza/swampcastle/releases/tag/v4.1.0
[4.0.2]: https://github.com/dekoza/swampcastle/releases/tag/v4.0.2
[4.0.0]: https://github.com/dekoza/swampcastle/releases/tag/v4.0.0
