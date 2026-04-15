from pathlib import Path

_RELEASE_VERSION = "4.1.0"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_project_version_is_bumped_to_release_target():
    pyproject = (_repo_root() / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{_RELEASE_VERSION}"' in pyproject


def test_changelog_contains_release_entry_and_links():
    changelog = (_repo_root() / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{_RELEASE_VERSION}] - " in changelog
    assert (
        f"[Unreleased]: https://github.com/dekoza/swampcastle/compare/v{_RELEASE_VERSION}...HEAD"
        in changelog
    )
    assert (
        f"[{_RELEASE_VERSION}]: https://github.com/dekoza/swampcastle/releases/tag/v{_RELEASE_VERSION}"
        in changelog
    )


def test_release_draft_exists_for_target_version():
    draft_path = _repo_root() / "docs" / "releases" / f"{_RELEASE_VERSION}-draft.md"
    assert draft_path.exists(), f"Missing release draft: {draft_path}"

    content = draft_path.read_text(encoding="utf-8")
    assert content.startswith(f"# SwampCastle {_RELEASE_VERSION}")
    assert "Draft — do not publish yet." not in content
    assert "## Highlights" in content
    assert "## Suggested release title" not in content
