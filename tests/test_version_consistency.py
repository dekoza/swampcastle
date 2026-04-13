import re
from pathlib import Path

from swampcastle import __version__
from swampcastle.version import PackageNotFoundError, _version_from_pyproject, get_version


def _expected_version() -> str:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    assert match is not None, "Could not find project version in pyproject.toml"
    return match.group(1)


def test_package_version_matches_pyproject():
    assert __version__ == _expected_version()


def test_version_helper_reads_pyproject():
    assert _version_from_pyproject() == _expected_version()


def test_get_version_falls_back_to_pyproject(monkeypatch):
    def missing(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr("swampcastle.version.metadata_version", missing)
    assert get_version() == _expected_version()
