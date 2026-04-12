"""SwampCastle error hierarchy.

All expected errors inherit from CastleError. Boundary handlers (MCP, CLI)
catch CastleError and convert to appropriate responses. Unexpected errors
bubble up as-is.
"""


class CastleError(Exception):
    """Base for all expected swampcastle errors."""

    code: str = "CASTLE_ERROR"


class NoCastleError(CastleError):
    """No castle found at the configured path."""

    code = "NO_CASTLE"


class StorageError(CastleError):
    """Backend storage failure (LanceDB, SQLite, Postgres)."""

    code = "STORAGE"


class ValidationError(CastleError):
    """Input validation failure (bad wing name, content too long, etc.)."""

    code = "VALIDATION"


class EmbedderError(CastleError):
    """Embedding model failure (missing model, dimension mismatch)."""

    code = "EMBEDDER"


class SyncConflictError(CastleError):
    """Sync conflict that could not be auto-resolved."""

    code = "SYNC_CONFLICT"
