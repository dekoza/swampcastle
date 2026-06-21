import logging
import os
import sqlite3
from pathlib import Path

from swampcastle.runtime_config import ensure_runtime_config
from swampcastle.settings import CastleSettings

logger = logging.getLogger("swampcastle.cli.commands")

DESKELETON_BATCH_SIZE = 1000


# ═══════════════════════════════════════════════════════════════════════
# Region: Shared helpers (DeskeletonTargetStore, _settings, _print_*)
# ═══════════════════════════════════════════════════════════════════════

class DeskeletonTargetStore:
    """SQLite-backed temporary store for unique deskeleton targets."""

    def __init__(self, path: str | Path):
        self._path = str(path)
        self._conn = sqlite3.connect(self._path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS deskeleton_targets (
                wing TEXT NOT NULL,
                source_file TEXT NOT NULL,
                PRIMARY KEY (wing, source_file)
            )
            """
        )

    def add(self, wing: str, source_file: str) -> bool:
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO deskeleton_targets (wing, source_file) VALUES (?, ?)",
            (wing, source_file),
        )
        return cursor.rowcount == 1

    def count(self) -> int:
        self._conn.commit()
        row = self._conn.execute("SELECT COUNT(*) FROM deskeleton_targets").fetchone()
        return int(row[0] if row is not None else 0)

    def iter_targets(self):
        self._conn.commit()
        cursor = self._conn.execute(
            "SELECT wing, source_file FROM deskeleton_targets ORDER BY wing, source_file"
        )
        yield from cursor

    def close(self) -> None:
        self._conn.close()


def _print_section(title: str) -> None:
    print(f"  SwampCastle {title}")


def _print_kv(label: str, value) -> None:
    print(f"  {label}: {value}")


def _render_progress_bar(processed: int, total: int, width: int = 24) -> str:
    if total <= 0:
        return "[------------------------]   0% 0/0"
    ratio = min(max(processed / total, 0.0), 1.0)
    filled = int(ratio * width)
    bar = "#" * filled + "-" * (width - filled)
    percent = int(ratio * 100)
    return f"[{bar}] {percent:3d}% {processed}/{total}"


def _print_progress(prefix: str, processed: int, total: int) -> None:
    end = "\n" if total > 0 and processed >= total else ""
    print(f"\r  {prefix}: {_render_progress_bar(processed, total)}", end=end, flush=True)


def _settings(args) -> CastleSettings:
    kwargs = {}
    palace = getattr(args, "palace", None)
    if palace:
        kwargs["castle_path"] = palace
    backend = getattr(args, "backend", None)
    if backend:
        kwargs["backend"] = backend
    config_path = ensure_runtime_config()
    return CastleSettings(_env_file=None, _json_file=str(config_path), **kwargs)
