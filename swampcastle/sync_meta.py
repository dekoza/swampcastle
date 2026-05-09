"""
sync_meta.py — Node identity and sync metadata for multi-device replication.

Each SwampCastle installation gets a unique node_id (generated once, persisted).
Every write operation gets a monotonically increasing sequence number and a
UTC timestamp.  These three fields enable the sync protocol (Phase 4) to
efficiently exchange only new/changed records between nodes.

Files:
    ~/.swampcastle/node_id   — 12-char hex string, generated once
    ~/.swampcastle/seq       — integer, incremented on every write

Metadata injected into every record:
    node_id:    str   — which machine wrote this record
    seq:        int   — monotonic counter on that machine
    updated_at: str   — ISO 8601 UTC wall clock time
"""

import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import uuid4

try:
    import fcntl

    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

try:
    import msvcrt

    _HAS_MSVCRT = True
except ImportError:
    _HAS_MSVCRT = False


class NodeIdentity:
    """Manages the node_id and sequence counter for this machine.

    Thread-safe sequence counter using file locking.
    """

    def __init__(self, config_dir: str = None):
        self._dir = Path(config_dir) if config_dir else Path(os.path.expanduser("~/.swampcastle"))
        self._dir.mkdir(parents=True, exist_ok=True)
        self._node_id_file = self._dir / "node_id"
        self._seq_file = self._dir / "seq"
        self._node_id = None

    @property
    def node_id(self) -> str:
        """Return this machine's unique node_id.  Generated once, then persisted."""
        if self._node_id is not None:
            return self._node_id

        if self._node_id_file.exists():
            self._node_id = self._node_id_file.read_text().strip()
        else:
            self._node_id = uuid4().hex[:12]
            self._node_id_file.write_text(self._node_id)
            try:
                self._node_id_file.chmod(0o600)
            except (OSError, NotImplementedError):
                pass

        return self._node_id

    @staticmethod
    def _lock(fd):
        if _HAS_FCNTL:
            fcntl.flock(fd, fcntl.LOCK_EX)
        elif _HAS_MSVCRT:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 4096)

    @staticmethod
    def _unlock(fd):
        if _HAS_FCNTL:
            fcntl.flock(fd, fcntl.LOCK_UN)
        elif _HAS_MSVCRT:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 4096)

    def next_seq(self, count: int = 1) -> int:
        """Atomically increment and return the sequence counter.

        Args:
            count: How many sequence numbers to allocate (default 1).
                   Returns the *first* allocated number; caller uses
                   first..first+count-1.

        Uses file locking so concurrent processes on the same machine
        don't collide.
        """
        self._dir.mkdir(parents=True, exist_ok=True)

        # Open-or-create the seq file
        fd = os.open(str(self._seq_file), os.O_RDWR | os.O_CREAT)
        try:
            self._lock(fd)
            data = os.read(fd, 64)
            current = int(data.strip()) if data.strip() else 0
            first = current + 1
            new_val = current + count
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, str(new_val).encode())
        finally:
            self._unlock(fd)
            os.close(fd)

        return first

    def current_seq(self) -> int:
        """Read the current sequence counter without incrementing."""
        if not self._seq_file.exists():
            return 0
        try:
            return int(self._seq_file.read_text().strip())
        except (ValueError, OSError):
            return 0


def utcnow_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ── Module-level singleton ────────────────────────────────────────────────────

_identity: NodeIdentity | None = None


def get_identity(config_dir: str = None) -> NodeIdentity:
    """Get or create the module-level NodeIdentity singleton."""
    global _identity
    if _identity is None or config_dir is not None:
        _identity = NodeIdentity(config_dir)
    return _identity


def inject_sync_meta(metadatas: list[dict], identity: NodeIdentity = None) -> list[dict]:
    """Inject node_id, seq, and updated_at into a batch of metadata dicts.

    Each record in the batch gets a unique seq number.
    Returns new list (does not mutate originals).
    """
    if identity is None:
        identity = get_identity()

    now = utcnow_iso()
    first_seq = identity.next_seq(count=len(metadatas))

    result = []
    for i, meta in enumerate(metadatas):
        m = dict(meta)
        m["node_id"] = identity.node_id
        m["seq"] = first_seq + i
        m["updated_at"] = now
        result.append(m)

    return result


class NodeStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    WIPE_REQUIRED = "wipe_required"


@runtime_checkable
class NodeStatusStore(Protocol):
    """Protocol for reading and writing node lifecycle status."""

    def get_status(self, node_id: str) -> NodeStatus: ...

    def set_status(self, node_id: str, status: NodeStatus) -> None: ...


class InMemoryNodeStatusStore:
    """Dict-backed store for tests and simple deployments."""

    def __init__(self) -> None:
        self._statuses: dict[str, NodeStatus] = {}

    def get_status(self, node_id: str) -> NodeStatus:
        return self._statuses.get(node_id, NodeStatus.ACTIVE)

    def set_status(self, node_id: str, status: NodeStatus) -> None:
        self._statuses[node_id] = status


class JsonFileNodeStatusStore:
    """JSON-file-backed store for persistent runtimes."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._statuses = self._load()

    def get_status(self, node_id: str) -> NodeStatus:
        raw = self._statuses.get(node_id)
        if raw is None:
            return NodeStatus.ACTIVE
        return NodeStatus(raw)

    def set_status(self, node_id: str, status: NodeStatus) -> None:
        self._statuses[node_id] = status.value
        self._save()

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._statuses, sort_keys=True), encoding="utf-8")
