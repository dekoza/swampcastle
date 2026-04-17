"""Tests for sync server authentication.

Bug: sync server endpoints (/sync/push and /sync/pull) have no authentication.
Any client that can reach the host can read or write all drawer data.

Fix: optional token-based auth via SWAMPCASTLE_SYNC_API_KEY env var /
settings field. When the key is set, all sync endpoints require an
'Authorization: Bearer <key>' header and return 401 otherwise.

References: docs/reviews/architecture_critical_review.md §6
"""

import unittest.mock as mock
from contextlib import contextmanager

import pytest

pytest.importorskip("fastapi", reason="fastapi required for sync server tests")

from fastapi.testclient import TestClient  # noqa: E402

from swampcastle.sync import ChangeSet, MergeResult, SyncEngine  # noqa: E402
from swampcastle.sync_server import create_app  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_engine() -> mock.MagicMock:
    engine = mock.MagicMock(spec=SyncEngine)
    engine._identity = mock.MagicMock(node_id="test-node")
    engine._col = mock.MagicMock()
    engine._col.count.return_value = 0
    engine.version_vector = {}
    engine.get_changes_since.return_value = ChangeSet(source_node="test-node")
    engine.count_changes_since.return_value = 0
    engine.apply_changes.return_value = MergeResult(accepted=0)
    return engine


@contextmanager
def _client(api_key: str | None):
    """TestClient with a fully mocked engine and controlled API key."""
    app = create_app()
    fake_engine = _make_fake_engine()
    with (
        mock.patch("swampcastle.sync_server._get_engine", return_value=fake_engine),
        mock.patch("swampcastle.sync_server._get_sync_api_key", return_value=api_key),
    ):
        with TestClient(app, raise_server_exceptions=True) as client:
            yield client


# ---------------------------------------------------------------------------
# Without authentication configured — all requests pass through
# ---------------------------------------------------------------------------


class TestSyncNoAuth:
    def test_health_ok_without_key(self):
        with _client(None) as c:
            assert c.get("/health").status_code == 200

    def test_status_ok_without_key(self):
        with _client(None) as c:
            assert c.get("/sync/status").status_code == 200

    def test_push_ok_without_key(self):
        with _client(None) as c:
            assert c.post("/sync/push", json={"source_node": "n", "records": []}).status_code == 200

    def test_pull_ok_without_key(self):
        with _client(None) as c:
            assert c.post("/sync/pull", json={"version_vector": {}}).status_code == 200


# ---------------------------------------------------------------------------
# With authentication configured — missing/wrong token → 401
# ---------------------------------------------------------------------------


class TestSyncWithAuth:
    def test_health_still_public_with_key_configured(self):
        """Health check must remain unauthenticated even when auth is enabled."""
        with _client("secret-token") as c:
            assert c.get("/health").status_code == 200

    def test_status_requires_auth(self):
        with _client("secret-token") as c:
            assert c.get("/sync/status").status_code == 401

    def test_push_requires_auth(self):
        with _client("secret-token") as c:
            resp = c.post("/sync/push", json={"source_node": "n", "records": []})
            assert resp.status_code == 401

    def test_pull_requires_auth(self):
        with _client("secret-token") as c:
            resp = c.post("/sync/pull", json={"version_vector": {}})
            assert resp.status_code == 401

    def test_wrong_token_returns_401(self):
        with _client("secret-token") as c:
            resp = c.get("/sync/status", headers={"Authorization": "Bearer wrong-token"})
            assert resp.status_code == 401

    def test_correct_token_grants_access_to_status(self):
        with _client("secret-token") as c:
            resp = c.get("/sync/status", headers={"Authorization": "Bearer secret-token"})
            assert resp.status_code == 200

    def test_correct_token_grants_access_to_push(self):
        with _client("secret-token") as c:
            resp = c.post(
                "/sync/push",
                json={"source_node": "n", "records": []},
                headers={"Authorization": "Bearer secret-token"},
            )
            assert resp.status_code == 200

    def test_correct_token_grants_access_to_pull(self):
        with _client("secret-token") as c:
            resp = c.post(
                "/sync/pull",
                json={"version_vector": {}},
                headers={"Authorization": "Bearer secret-token"},
            )
            assert resp.status_code == 200

    def test_prefix_token_rejected(self):
        """A token that is a prefix of the real token must not be accepted."""
        with _client("secret-token") as c:
            resp = c.get("/sync/status", headers={"Authorization": "Bearer secret"})
            assert resp.status_code == 401

    def test_empty_bearer_rejected(self):
        with _client("secret-token") as c:
            resp = c.get("/sync/status", headers={"Authorization": "Bearer "})
            assert resp.status_code == 401

    def test_malformed_authorization_header_rejected(self):
        with _client("secret-token") as c:
            resp = c.get("/sync/status", headers={"Authorization": "secret-token"})
            assert resp.status_code == 401
