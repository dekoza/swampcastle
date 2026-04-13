"""Package version helpers.

The project version lives in ``pyproject.toml`` and should be bumped with
``uv version`` / ``uv version --bump ...``.

At runtime we prefer installed package metadata. When importing directly from a
source checkout without installed metadata, we fall back to reading the project
version from ``pyproject.toml``.
"""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version as metadata_version
from pathlib import Path

_PACKAGE_NAME = "swampcastle"
_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def _version_from_pyproject() -> str:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    match = _VERSION_RE.search(content)
    if match is None:
        raise RuntimeError("Could not find project version in pyproject.toml")
    return match.group(1)


def get_version() -> str:
    """Return the package version from installed metadata or pyproject."""
    try:
        return metadata_version(_PACKAGE_NAME)
    except PackageNotFoundError:
        return _version_from_pyproject()


__version__ = get_version()
