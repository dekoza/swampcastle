"""Contributor detection for project files.

Resolves file contributors against the project team list and the global
entity registry so ingested drawers can be tagged with who wrote them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def detect_contributor(
    filepath: Path,
    project_path: Path,
    team: list[str] | None = None,
    registry=None,
) -> str | None:
    """Detect who last modified a file using git log.

    Returns the team member identifier if matched, or None.
    """
    if not team:
        return None

    author = _git_last_author(filepath, project_path)
    if not author:
        return None

    author_lower = author.lower()

    # Direct match against team list
    for member in team:
        if member.lower() == author_lower:
            return member

    # Partial match: team member name appears in git author string
    for member in team:
        if member.lower() in author_lower or author_lower in member.lower():
            return member

    # Check if author matches self identity
    if registry is not None:
        if registry.is_self(author):
            identity = registry.self_identity
            return identity.get("nickname") or identity.get("name") or author

    return None


def _git_last_author(filepath: Path, project_path: Path) -> str | None:
    """Get the last git committer of a file. Returns None if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%an", "--", str(filepath)],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(project_path),
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None
