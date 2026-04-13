"""Interactive wizard for global SwampCastle runtime configuration."""

from __future__ import annotations

from swampcastle.runtime_config import load_runtime_config, save_runtime_config


def _prompt(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    value = input(f"  {prompt}{suffix}: ").strip()
    if value:
        return value
    return default or ""


def run_wizard() -> None:
    config = load_runtime_config()

    print("  SwampCastle Wizard")
    print("  Configure global runtime settings.")

    backend = _prompt("Backend (lance/postgres)", str(config.get("backend", "lance"))).lower()
    while backend not in {"lance", "postgres"}:
        print("  Please enter 'lance' or 'postgres'.")
        backend = _prompt("Backend (lance/postgres)", str(config.get("backend", "lance"))).lower()

    castle_path = _prompt("Castle path", str(config.get("castle_path", "")))

    updated = {
        "castle_path": castle_path,
        "backend": backend,
        "collection_name": config.get("collection_name", "swampcastle_chests"),
        "embedder": config.get("embedder", "onnx"),
    }

    if backend == "postgres":
        database_url = _prompt("Database URL", str(config.get("database_url", "")))
        while not database_url:
            print("  PostgreSQL requires a database URL.")
            database_url = _prompt("Database URL", str(config.get("database_url", "")))
        updated["database_url"] = database_url

    config_path = save_runtime_config(updated)
    print(f"  Saved runtime config: {config_path}")
