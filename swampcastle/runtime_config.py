"""Bootstrap helpers for global SwampCastle runtime config."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RUNTIME_CONFIG_DIRNAME = ".swampcastle"
RUNTIME_CONFIG_FILENAME = "config.json"


def runtime_config_dir() -> Path:
    return Path.home() / RUNTIME_CONFIG_DIRNAME


def runtime_config_path() -> Path:
    return runtime_config_dir() / RUNTIME_CONFIG_FILENAME


def _default_runtime_config() -> dict[str, str]:
    base = runtime_config_dir()
    return {
        "castle_path": str(base / "castle"),
        "backend": "lance",
        "collection_name": "swampcastle_chests",
        "embedder": "onnx",
    }


def _has_legacy_mempalace_remnants(home: Path | None = None) -> bool:
    home = home or Path.home()
    legacy_palace = home / ".mempalace" / "palace"
    default_legacy_swamp = home / ".swampcastle" / "palace"
    return (
        legacy_palace.exists()
        or (legacy_palace / "chroma.sqlite3").exists()
        or (default_legacy_swamp / "chroma.sqlite3").exists()
    )


def load_runtime_config() -> dict[str, Any]:
    config_path = ensure_runtime_config()
    return json.loads(config_path.read_text(encoding="utf-8"))


def save_runtime_config(config: dict[str, Any]) -> Path:
    config_path = runtime_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config_path


def ensure_runtime_config() -> Path:
    """Create the default runtime config on first use and return its path."""
    config_path = runtime_config_path()
    if config_path.exists():
        return config_path

    save_runtime_config(_default_runtime_config())

    print(f"  Created default runtime config: {config_path}")
    print("  Backend: lance")
    print("  Run 'swampcastle wizard' to customize backend or storage settings.")

    if _has_legacy_mempalace_remnants():
        print()
        print("  Legacy MemPalace data was detected.")
        print("  Recommended next step: swampcastle migrate")
        print("  If you want PostgreSQL instead, run swampcastle wizard before migrating.")

    return config_path
