"""Helpers for project-local SwampCastle config files."""

from __future__ import annotations

from pathlib import Path

PROJECT_CONFIG_NAME = ".swampcastle.yaml"
LEGACY_PROJECT_CONFIG_NAME = "swampcastle.yaml"


def project_config_path(project_dir: str | Path) -> Path:
    return Path(project_dir).expanduser().resolve() / PROJECT_CONFIG_NAME


def legacy_project_config_path(project_dir: str | Path) -> Path:
    return Path(project_dir).expanduser().resolve() / LEGACY_PROJECT_CONFIG_NAME


def resolve_project_config(project_dir: str | Path) -> Path | None:
    """Resolve the active project config path and migrate legacy name if needed.

    Rules:
    - prefer .swampcastle.yaml
    - if only swampcastle.yaml exists, rename it and print a migration message
    - if both exist, prefer .swampcastle.yaml and leave legacy file untouched
    """
    config_path = project_config_path(project_dir)
    legacy_path = legacy_project_config_path(project_dir)

    if config_path.exists():
        if legacy_path.exists():
            print(
                f"  Warning: detected both {PROJECT_CONFIG_NAME} and {LEGACY_PROJECT_CONFIG_NAME}; "
                f"using {PROJECT_CONFIG_NAME} and ignoring the legacy file."
            )
        return config_path

    if legacy_path.exists():
        legacy_path.replace(config_path)
        print(
            f"  Migrated legacy project config: {LEGACY_PROJECT_CONFIG_NAME} -> "
            f"{PROJECT_CONFIG_NAME}"
        )
        return config_path

    return None
