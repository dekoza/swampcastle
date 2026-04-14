from pathlib import Path
from swampcastle.mining.miner import scan_project


def test_global_swampignore(tmp_path, monkeypatch):
    # make fake HOME
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)

    # global ignore file in HOME
    (home / ".swampcastleignore").write_text("ignoreme.txt\n")

    project = tmp_path / "project"
    project.mkdir()
    keep = project / "keep.txt"
    keep.write_text("ok")
    bad = project / "ignoreme.txt"
    bad.write_text("secret")

    files = scan_project(str(project))
    names = [p.name for p in files]
    assert "keep.txt" in names
    assert "ignoreme.txt" not in names


def test_project_swampcastleignore_negation_overrides_global_swampignore(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    (home / ".swampcastleignore").write_text("*.txt\n")

    project = tmp_path / "project"
    project.mkdir()
    (project / ".swampcastleignore").write_text("!keep.txt\n")
    (project / "keep.txt").write_text("keep me")
    (project / "drop.txt").write_text("drop me")

    files = scan_project(str(project))
    names = [p.name for p in files]
    assert "keep.txt" in names
    assert "drop.txt" not in names
