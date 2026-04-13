# Changelog

All notable changes to SwampCastle are documented in this file.

This project follows a simple versioned changelog format.

## [Unreleased]

- No unreleased changes yet.

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

[Unreleased]: https://github.com/dekoza/swampcastle/compare/v4.0.2...HEAD
[4.0.2]: https://github.com/dekoza/swampcastle/releases/tag/v4.0.2
[4.0.0]: https://github.com/dekoza/swampcastle/releases/tag/v4.0.0
