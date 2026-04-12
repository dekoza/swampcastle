"""Write-ahead log for auditing all castle write operations."""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("swampcastle.wal")


class WalWriter:
    """Append-only JSONL audit log for write operations.

    Every write (add_drawer, delete, kg_add, kg_invalidate, diary_write)
    is logged before execution. Provides an audit trail for detecting
    memory poisoning and reviewing writes from untrusted sources.
    """

    def __init__(self, wal_dir: Path):
        self._dir = Path(wal_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        try:
            self._dir.chmod(0o700)
        except (OSError, NotImplementedError):
            pass
        self._file = self._dir / "write_log.jsonl"

    def log(self, operation: str, params: dict, result: dict | None = None):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "params": params,
            "result": result,
        }
        try:
            with open(self._file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
            try:
                self._file.chmod(0o600)
            except (OSError, NotImplementedError):
                pass
        except Exception as e:
            logger.error("WAL write failed: %s", e)

    def read_entries(self) -> list[dict]:
        if not self._file.exists():
            return []
        entries = []
        with open(self._file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries
