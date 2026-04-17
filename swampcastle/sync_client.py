"""
sync_client.py — HTTP client for syncing with a remote SwampCastle server.

Usage:
    from swampcastle.sync_client import SyncClient
    client = SyncClient("http://homeserver:7433")
    client.sync(engine)           # push + pull
    client.is_reachable()         # health check

Optional auth:
    export SWAMPCASTLE_SYNC_API_KEY=secret
    client = SyncClient("http://homeserver:7433")
    # or: SyncClient("http://homeserver:7433", api_key="secret")
"""

from __future__ import annotations

import gzip
import json
import logging
import os
from urllib.request import Request, urlopen

from .sync import ChangeSet, SyncEngine

logger = logging.getLogger("swampcastle.sync_client")

_SYNC_GZIP_MIN_BYTES = 4096
_SYNC_GZIP_COMPRESSLEVEL = 6
DEFAULT_SYNC_PAGE_SIZE = 500


class SyncClient:
    """HTTP client that talks to a swampcastle sync server."""

    def __init__(
        self,
        server_url: str,
        timeout: float = 30.0,
        api_key: str | None = None,
    ):
        self._url = server_url.rstrip("/")
        self._timeout = timeout
        self._api_key = (
            api_key if api_key is not None else os.environ.get("SWAMPCASTLE_SYNC_API_KEY")
        )
        self._server_supports_gzip_requests = False

    def _request(self, method: str, path: str, body: dict = None) -> dict:
        """Make an HTTP request and return parsed JSON."""
        url = f"{self._url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Accept-Encoding": "gzip"}
        if data is not None:
            headers["Content-Type"] = "application/json"
            if self._server_supports_gzip_requests and len(data) >= _SYNC_GZIP_MIN_BYTES:
                data = gzip.compress(data, compresslevel=_SYNC_GZIP_COMPRESSLEVEL)
                headers["Content-Encoding"] = "gzip"
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = Request(url, data=data, headers=headers, method=method)
        with urlopen(req, timeout=self._timeout) as resp:
            raw = resp.read()
            content_encoding = getattr(resp, "headers", {}).get("Content-Encoding", "")
            if "gzip" in content_encoding.lower():
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))

    def is_reachable(self) -> bool:
        """Check if the server is reachable."""
        try:
            r = self._request("GET", "/health")
            return r.get("status") == "ok"
        except Exception:
            return False

    def get_status(self) -> dict:
        """Get server's node_id, version_vector, and drawer count."""
        status = self._request("GET", "/sync/status")
        capabilities = status.get("capabilities") or {}
        self._server_supports_gzip_requests = bool(capabilities.get("gzip_request_bodies"))
        return status

    def push(self, changeset: ChangeSet) -> dict:
        """Send a changeset to the server."""
        return self._request("POST", "/sync/push", changeset.to_dict())

    def pull(self, local_vv: dict[str, int]) -> ChangeSet:
        """Request records the local node hasn't seen (single unpaginated request)."""
        resp = self._request("POST", "/sync/pull", {"version_vector": local_vv})
        return ChangeSet.from_dict(resp)

    def pull_paged(
        self,
        local_vv: dict[str, int],
        *,
        page_size: int | None = None,
    ) -> ChangeSet:
        """Pull all changes from the server using paginated requests.

        Loops until the server reports has_more=False.  The same version
        vector is sent on every page request so the result set is stable
        for the duration of the sync session.
        """
        page_size = page_size or DEFAULT_SYNC_PAGE_SIZE
        source_node = ""
        raw_records: list[dict] = []
        offset = 0

        while True:
            resp = self._request(
                "POST",
                "/sync/pull",
                {"version_vector": local_vv, "limit": page_size, "offset": offset},
            )
            source_node = resp.get("source_node", source_node)
            page = resp.get("records", [])
            raw_records.extend(page)

            if not resp.get("has_more", False):
                break
            offset += page_size

        return ChangeSet.from_dict({"source_node": source_node, "records": raw_records})

    def sync(self, engine: SyncEngine) -> dict:
        """Full bidirectional sync: push our changes, then pull theirs.

        Returns a summary dict.
        """
        # 1. Get server status
        status = self.get_status()
        server_protocol = status.get("protocol_version")
        if server_protocol is not None and server_protocol not in ["2025-03-26", "2024-11-05"]:
            raise ValueError(f"Incompatible or missing protocol version: {server_protocol}")
        server_vv = status["version_vector"]
        server_node = status["node_id"]

        logger.info(
            "Sync start — server=%s drawers=%d",
            server_node,
            status["total_drawers"],
        )

        # 2. Push: send records the server hasn't seen
        changeset = engine.get_changes_since(server_vv)
        push_result = {"sent": 0, "accepted": 0, "rejected": 0}
        if changeset.records:
            resp = self.push(changeset)
            push_result = {
                "sent": len(changeset.records),
                "accepted": resp.get("accepted", 0),
                "rejected": resp.get("rejected_conflicts", 0),
            }
            logger.info(
                "Push: sent=%d accepted=%d rejected=%d",
                push_result["sent"],
                push_result["accepted"],
                push_result["rejected"],
            )

        # 3. Pull: get records we haven't seen
        local_vv = engine.version_vector
        remote_changes = self.pull_paged(local_vv)
        pull_result = {"received": 0, "accepted": 0, "rejected": 0}
        if remote_changes.records:
            merge = engine.apply_changes(remote_changes)
            pull_result = {
                "received": len(remote_changes.records),
                "accepted": merge.accepted,
                "rejected": merge.rejected_conflicts,
            }
            logger.info(
                "Pull: received=%d accepted=%d rejected=%d",
                pull_result["received"],
                pull_result["accepted"],
                pull_result["rejected"],
            )

        return {
            "server": server_node,
            "push": push_result,
            "pull": pull_result,
            "local_vv": engine.version_vector,
        }
