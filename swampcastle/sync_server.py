"""
sync_server.py — HTTP sync server for multi-device SwampCastle replication.

Run with:  swampcastle garrison --host 0.0.0.0 --port 7433

Authentication (optional)
--------------------------
Set SWAMPCASTLE_SYNC_API_KEY to a random secret string.  When set, every
sync endpoint (/sync/status, /sync/push, /sync/pull) requires an HTTP header::

    Authorization: Bearer <your-key>

/health remains unauthenticated to support load-balancer probes.

Leaving SWAMPCASTLE_SYNC_API_KEY unset keeps the server open — fine for a
trusted private LAN; required for internet-facing deployments.

Endpoints:
    GET  /health       — server health check
    GET  /sync/status  — version vector + record count
    POST /sync/push    — receive records from a client
    POST /sync/pull    — send records the client hasn't seen
"""

import atexit
import hmac
import logging
import os
from contextlib import asynccontextmanager

from .settings import CastleSettings as CastleConfig
from .storage import factory_from_settings
from .sync import ChangeSet, SyncEngine, SyncRecord
from .sync_meta import get_identity
from .version import __version__

logger = logging.getLogger("swampcastle.sync_server")


# ── Auth helpers ──────────────────────────────────────────────────────────────


def _get_sync_api_key() -> str | None:
    """Return the configured sync API key, or None if auth is disabled.

    Reads SWAMPCASTLE_SYNC_API_KEY directly from the environment on every
    call so the key can be rotated at runtime without restarting the server.
    This avoids constructing a CastleSettings object on every request.
    """
    return os.environ.get("SWAMPCASTLE_SYNC_API_KEY") or None


def _check_bearer(authorization: str | None, expected: str) -> bool:
    """Validate an Authorization: Bearer <token> header using constant-time comparison."""
    if not authorization:
        return False
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    token = parts[1].strip()
    if not token:
        return False
    return hmac.compare_digest(token, expected)


# ── Lazy globals (initialised on first request) ───────────────────────────────

_engine = None
_config = None
_factory = None


def _shutdown_engine() -> None:
    """Clean up the cached sync engine and factory.

    Call this on application shutdown to release resources (database connections,
    file handles, etc.). Registered with atexit as a fallback.
    """
    global _engine, _config, _factory
    if _factory is not None:
        try:
            _factory.close()
        except Exception as e:
            logger.warning("Error closing factory during shutdown: %s", e)
        _factory = None
    _engine = None
    _config = None
    logger.debug("Sync engine shutdown complete")


# Register shutdown with atexit as fallback for non-FastAPI usage
atexit.register(_shutdown_engine)


def _get_engine() -> SyncEngine:
    global _engine, _config, _factory
    if _engine is None:
        _config = CastleConfig(_env_file=None)
        palace_path = _config.castle_path

        try:
            _factory = factory_from_settings(_config)
        except NotImplementedError as exc:
            raise RuntimeError(
                f"Castle at {palace_path} uses ChromaDB. "
                "Sync does not support ChromaDB. Run: swampcastle raise"
            ) from exc
        except ValueError as exc:
            raise RuntimeError(f"Invalid configuration for sync server: {exc}") from exc
        except ImportError as exc:
            raise RuntimeError(
                f"Missing dependency for configured backend: {exc}. Check your installation."
            ) from exc
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Castle path not found: {palace_path}. Run 'swampcastle build' first."
            ) from exc

        os.makedirs(str(palace_path), exist_ok=True)
        col = _factory.open_collection(_config.collection_name)
        identity = get_identity(str(_config.config_dir))
        vv_path = os.path.join(str(palace_path), "version_vector.json")

        _engine = SyncEngine(col, identity=identity, vv_path=vv_path)
        logger.info(
            "Sync engine initialised — node=%s backend=%s castle=%s",
            identity.node_id,
            _config.backend,
            palace_path,
        )
    return _engine


# ── FastAPI app ───────────────────────────────────────────────────────────────


@asynccontextmanager
async def _lifespan(app):
    """FastAPI lifespan for proper engine cleanup on shutdown."""
    yield
    _shutdown_engine()


def create_app():
    """Create the FastAPI application."""
    try:
        from fastapi import FastAPI, HTTPException, Request
    except ImportError:
        raise ImportError(
            "fastapi is required for the sync server. Install with: pip install 'swampcastle[server]'"
        )

    app = FastAPI(
        title="Swamp Castle Sync Server",
        version=__version__,
        lifespan=_lifespan,
    )

    # ── Endpoints ─────────────────────────────────────────────────────

    def _require_auth(request: Request):
        """Enforce Bearer token when sync_api_key is set.

        Defined inside create_app() so it closes over HTTPException from the
        optional fastapi dependency (avoiding a module-level import of an
        optional package).
        """
        api_key = _get_sync_api_key()
        if api_key is None:
            return
        auth_header = request.headers.get("Authorization")
        if not _check_bearer(auth_header, api_key):
            raise HTTPException(status_code=401, detail="Invalid or missing authorization token")

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "swampcastle-sync"}

    @app.get("/sync/status")
    def sync_status(request: Request):
        _require_auth(request)
        engine = _get_engine()
        col = engine._col
        return {
            "node_id": engine._identity.node_id,
            "version_vector": engine.version_vector,
            "total_drawers": col.count(),
        }

    @app.post("/sync/push")
    async def sync_push(request: Request):  # noqa: F811
        _require_auth(request)
        body = await request.json()
        engine = _get_engine()
        cs = ChangeSet(
            source_node=body.get("source_node", ""),
            records=[SyncRecord.from_dict(r) for r in body.get("records", [])],
        )
        result = engine.apply_changes(cs)
        return {
            "accepted": result.accepted,
            "rejected_conflicts": result.rejected_conflicts,
            "errors": result.errors,
        }

    @app.post("/sync/pull")
    async def sync_pull(request: Request):  # noqa: F811
        _require_auth(request)
        body = await request.json()
        engine = _get_engine()
        cs = engine.get_changes_since(body.get("version_vector", {}))
        return {
            "source_node": cs.source_node,
            "records": [r.to_dict() for r in cs.records],
        }

    return app
