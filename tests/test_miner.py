import os
import shutil
import tempfile
from pathlib import Path

import yaml

from swampcastle.mining.miner import _file_already_mined as file_already_mined
from swampcastle.mining.miner import mine, scan_project
from swampcastle.storage.lance import LanceBackend
from swampcastle.storage.memory import InMemoryStorageFactory


def _get_test_collection(path, name="swampcastle_chests"):
    return LanceBackend().get_collection(path, name, create=True)


def write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def scanned_files(project_root: Path, **kwargs):
    files = scan_project(str(project_root), **kwargs)
    return sorted(path.relative_to(project_root).as_posix() for path in files)


def test_project_mining():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        os.makedirs(project_root / "backend")

        write_file(
            project_root / "backend" / "app.py", "def main():\n    print('hello world')\n" * 20
        )
        with open(project_root / ".swampcastle.yaml", "w") as f:
            yaml.dump(
                {
                    "wing": "test_project",
                    "rooms": [
                        {"name": "backend", "description": "Backend code"},
                        {"name": "general", "description": "General"},
                    ],
                },
                f,
            )

        palace_path = project_root / "palace"
        mine(str(project_root), str(palace_path))

        col = _get_test_collection(str(palace_path))
        assert col.count() > 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_project_mining_accepts_storage_factory():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        os.makedirs(project_root / "backend")

        write_file(
            project_root / "backend" / "app.py", "def main():\n    print('hello world')\n" * 20
        )
        with open(project_root / ".swampcastle.yaml", "w") as f:
            yaml.dump(
                {
                    "wing": "test_project",
                    "rooms": [
                        {"name": "backend", "description": "Backend code"},
                        {"name": "general", "description": "General"},
                    ],
                },
                f,
            )

        factory = InMemoryStorageFactory()
        mine(str(project_root), str(project_root / "palace"), storage_factory=factory)

        col = factory.open_collection("swampcastle_chests")
        assert col.count() > 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_project_mining_can_extract_kg_proposals():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        os.makedirs(project_root / "backend")

        write_file(
            project_root / "backend" / "auth.md",
            "We switched from Auth0 to Clerk because local testing got simpler.\n",
        )
        with open(project_root / ".swampcastle.yaml", "w") as f:
            yaml.dump(
                {
                    "wing": "test_project",
                    "rooms": [
                        {"name": "backend", "description": "Backend code"},
                        {"name": "general", "description": "General"},
                    ],
                },
                f,
            )

        factory = InMemoryStorageFactory()
        mine(
            str(project_root),
            str(project_root / "palace"),
            storage_factory=factory,
            extract_kg_proposals=True,
        )

        graph = factory.open_graph()
        proposals = graph.list_candidate_triples(status="proposed")
        assert len(proposals) >= 2
        predicates = {(row["predicate"], row["object_text"]) for row in proposals}
        assert ("migrated_from", "Auth0") in predicates
        assert ("migrated_to", "Clerk") in predicates
        # Proposal extraction must not auto-write accepted facts into the KG
        assert graph.query_entity(name="test_project", direction="outgoing") == []
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_scan_project_respects_gitignore():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "ignored.py\ngenerated/\n")
        write_file(project_root / "src" / "app.py", "print('hello')\n" * 20)
        write_file(project_root / "ignored.py", "print('ignore me')\n" * 20)
        write_file(project_root / "generated" / "artifact.py", "print('artifact')\n" * 20)

        assert scanned_files(project_root) == ["src/app.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_respects_nested_gitignore():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "*.log\n")
        write_file(project_root / "subrepo" / ".gitignore", "tasks/\n")
        write_file(project_root / "subrepo" / "src" / "main.py", "print('main')\n" * 20)
        write_file(project_root / "subrepo" / "tasks" / "task.py", "print('task')\n" * 20)
        write_file(project_root / "subrepo" / "debug.log", "debug\n" * 20)

        assert scanned_files(project_root) == ["subrepo/src/main.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_allows_nested_gitignore_override():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "*.csv\n")
        write_file(project_root / "subrepo" / ".gitignore", "!keep.csv\n")
        write_file(project_root / "drop.csv", "a,b,c\n" * 20)
        write_file(project_root / "subrepo" / "keep.csv", "a,b,c\n" * 20)

        assert scanned_files(project_root) == ["subrepo/keep.csv"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_allows_gitignore_negation_when_parent_dir_is_visible():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "generated/*\n!generated/keep.py\n")
        write_file(project_root / "generated" / "drop.py", "print('drop')\n" * 20)
        write_file(project_root / "generated" / "keep.py", "print('keep')\n" * 20)

        assert scanned_files(project_root) == ["generated/keep.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_does_not_reinclude_file_from_ignored_directory():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "generated/\n!generated/keep.py\n")
        write_file(project_root / "generated" / "drop.py", "print('drop')\n" * 20)
        write_file(project_root / "generated" / "keep.py", "print('keep')\n" * 20)

        assert scanned_files(project_root) == []
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_disable_gitignore():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "data/\n")
        write_file(project_root / "data" / "stuff.csv", "a,b,c\n" * 20)

        assert scanned_files(project_root, respect_gitignore=False) == ["data/stuff.csv"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_include_ignored_directory():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "docs/\n")
        write_file(project_root / "docs" / "guide.md", "# Guide\n" * 20)

        assert scanned_files(project_root, include_ignored=["docs"]) == ["docs/guide.md"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_include_specific_ignored_file():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "generated/\n")
        write_file(project_root / "generated" / "drop.py", "print('drop')\n" * 20)
        write_file(project_root / "generated" / "keep.py", "print('keep')\n" * 20)

        assert scanned_files(project_root, include_ignored=["generated/keep.py"]) == [
            "generated/keep.py"
        ]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_include_exact_file_without_known_extension():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "README\n")
        write_file(project_root / "README", "hello\n" * 20)

        assert scanned_files(project_root, include_ignored=["README"]) == ["README"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_include_override_beats_skip_dirs():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".pytest_cache" / "cache.py", "print('cache')\n" * 20)

        assert scanned_files(
            project_root,
            respect_gitignore=False,
            include_ignored=[".pytest_cache"],
        ) == [".pytest_cache/cache.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_skip_dirs_still_apply_without_override():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".pytest_cache" / "cache.py", "print('cache')\n" * 20)
        write_file(project_root / "main.py", "print('main')\n" * 20)

        assert scanned_files(project_root, respect_gitignore=False) == ["main.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_file_already_mined_check_mtime():
    tmpdir = tempfile.mkdtemp()
    try:
        palace_path = os.path.join(tmpdir, "palace")
        os.makedirs(palace_path)
        col = _get_test_collection(palace_path)

        test_file = os.path.join(tmpdir, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello world")

        mtime = os.path.getmtime(test_file)

        # Not mined yet
        assert file_already_mined(col, test_file) is False
        assert file_already_mined(col, test_file, check_mtime=True) is False

        # Add it with mtime
        col.add(
            ids=["d1"],
            documents=["hello world"],
            metadatas=[{"source_file": test_file, "source_mtime": str(mtime)}],
        )

        # Already mined (no mtime check)
        assert file_already_mined(col, test_file) is True
        # Already mined (mtime matches)
        assert file_already_mined(col, test_file, check_mtime=True) is True

        # Modify file and force a different mtime (Windows has low mtime resolution)
        with open(test_file, "w") as f:
            f.write("modified content")
        os.utime(test_file, (mtime + 10, mtime + 10))

        # Still mined without mtime check
        assert file_already_mined(col, test_file) is True
        # Needs re-mining with mtime check
        assert file_already_mined(col, test_file, check_mtime=True) is False

        # Record with no mtime stored should return False for check_mtime
        col.add(
            ids=["d2"],
            documents=["other"],
            metadatas=[{"source_file": "/fake/no_mtime.txt"}],
        )
        assert file_already_mined(col, "/fake/no_mtime.txt", check_mtime=True) is False
    finally:
        del col
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_project_mining_tags_contributor_metadata():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        os.makedirs(project_root / "backend")

        write_file(
            project_root / "backend" / "app.py",
            "def main():\n    print('hello world')\n" * 20,
        )
        with open(project_root / ".swampcastle.yaml", "w") as f:
            yaml.dump(
                {
                    "wing": "test_project",
                    "team": ["dekoza", "sarah"],
                    "rooms": [
                        {"name": "backend", "description": "Backend code"},
                        {"name": "general", "description": "General"},
                    ],
                },
                f,
            )

        factory = InMemoryStorageFactory()
        from unittest.mock import patch

        with patch(
            "swampcastle.mining.contributor._git_last_author",
            return_value="dekoza",
        ):
            mine(str(project_root), str(project_root / "palace"), storage_factory=factory)

        col = factory.open_collection("swampcastle_chests")
        rows = col.get(include=["metadatas"])
        assert rows["metadatas"]
        assert all(meta.get("contributor") == "dekoza" for meta in rows["metadatas"])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _file_drawers(collection, *, source_file: str, wing: str):
    return collection.get(
        where={"$and": [{"source_file": source_file}, {"wing": wing}]},
        include=["documents", "metadatas"],
    )


def test_remine_shrunk_file_replaces_old_chunks_in_memory(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_file(
        project_root / ".swampcastle.yaml",
        yaml.dump(
            {"wing": "test_project", "rooms": [{"name": "general", "description": "General"}]}
        ),
    )
    source = project_root / "notes.txt"
    write_file(source, "alpha line\n" * 1000)

    factory = InMemoryStorageFactory()

    mine(str(project_root), str(project_root / "palace"), storage_factory=factory)

    collection = factory.open_collection("swampcastle_chests")
    first = _file_drawers(collection, source_file=str(source), wing="test_project")
    assert len(first["ids"]) > 1

    write_file(source, "beta line\n" * 40)
    mine(str(project_root), str(project_root / "palace"), storage_factory=factory)

    second = _file_drawers(collection, source_file=str(source), wing="test_project")
    assert len(second["ids"]) == 1
    assert second["documents"] == [("beta line\n" * 40).strip()]


def test_remine_shrunk_file_replaces_old_chunks_in_lance(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_file(
        project_root / ".swampcastle.yaml",
        yaml.dump(
            {"wing": "test_project", "rooms": [{"name": "general", "description": "General"}]}
        ),
    )
    source = project_root / "notes.txt"
    write_file(source, "alpha line\n" * 1000)

    palace_path = project_root / "palace"
    mine(str(project_root), str(palace_path))

    collection = _get_test_collection(str(palace_path))
    first = _file_drawers(collection, source_file=str(source), wing="test_project")
    assert len(first["ids"]) > 1

    write_file(source, "beta line\n" * 40)
    mine(str(project_root), str(palace_path))

    collection = _get_test_collection(str(palace_path))
    second = _file_drawers(collection, source_file=str(source), wing="test_project")
    assert len(second["ids"]) == 1
    assert second["documents"] == [("beta line\n" * 40).strip()]


def test_remine_room_change_removes_old_room_chunks(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_file(
        project_root / ".swampcastle.yaml",
        yaml.dump(
            {
                "wing": "test_project",
                "rooms": [
                    {"name": "billing", "description": "Billing", "keywords": ["invoice"]},
                    {"name": "auth", "description": "Authentication", "keywords": ["token"]},
                    {"name": "general", "description": "General"},
                ],
            }
        ),
    )
    source = project_root / "shared.txt"
    write_file(source, ("invoice\n" * 500) + ("common\n" * 500))

    factory = InMemoryStorageFactory()
    mine(str(project_root), str(project_root / "palace"), storage_factory=factory)

    collection = factory.open_collection("swampcastle_chests")
    first = _file_drawers(collection, source_file=str(source), wing="test_project")
    assert {meta["room"] for meta in first["metadatas"]} == {"billing"}

    write_file(source, ("token\n" * 500) + ("common\n" * 500))
    mine(str(project_root), str(project_root / "palace"), storage_factory=factory)

    second = _file_drawers(collection, source_file=str(source), wing="test_project")
    assert {meta["room"] for meta in second["metadatas"]} == {"auth"}
