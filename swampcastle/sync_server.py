"""
sync_server.py — HTTP sync server for multi-device SwampCastle replication.

Run with:  swampcastle garrison --host 0.0.0.0 --port 7433

Endpoints:
    GET  /health       — server health check
    GET  /sync/status  — version vector + record count
    POST /sync/push    — receive records from a client
    POST /sync/pull    — send records the client hasn't seen
"""

import atexit
import logging
import os
from contextlib import asynccontextmanager

from .settings import CastleSettings as CastleConfig
from .storage import factory_from_settings
from .sync import SyncEngine, ChangeSet, SyncRecord
from .sync_meta import get_identity

logger = logging.getLogger("swampcastle.sync_server")

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
            raise RuntimeError(
                f"Invalid configuration for sync server: {exc}"
            ) from exc
        except ImportError as exc:
            raise RuntimeError(
                f"Missing dependency for configured backend: {exc}. "
                "Check your installation."
            ) from exc
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Castle path not found: {palace_path}. "
                "Run 'swampcastle build' first."
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
        from fastapi import FastAPI, Request
    except ImportError:
        raise ImportError(
            "fastapi is required for the sync server. Install with: pip install 'swampcastle[server]'"
        )

    app = FastAPI(
        title="Swamp Castle Sync Server",
        version="1.0.0",
        lifespan=_lifespan,
    )

    # ── Endpoints ─────────────────────────────────────────────────────

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "swampcastle-sync"}

    @app.get("/sync/status")
    def sync_status():
        engine = _get_engine()
        col = engine._col
        return {
            "node_id": engine._identity.node_id,
            "version_vector": engine.version_vector,
            "total_drawers": col.count(),
        }

    @app.post("/sync/push")
    async def sync_push(request: Request):  # noqa: F811
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
        body = await request.json()
        engine = _get_engine()
        cs = engine.get_changes_since(body.get("version_vector", {}))
        return {
            "source_node": cs.source_node,
            "records": [r.to_dict() for r in cs.records],
        }

    return app
