from pathlib import Path
from swampcastle.mining.miner import scan_project


def test_global_swampignore(tmp_path, monkeypatch):
    # make fake HOME
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setattr('pathlib.Path.home', lambda: home)

    # global ignore file in HOME
    (home / '.swampcastleignore').write_text('ignoreme.txt\n')

    project = tmp_path / 'project'
    project.mkdir()
    keep = project / 'keep.txt'
    keep.write_text('ok')
    bad = project / 'ignoreme.txt'
    bad.write_text('secret')

    files = scan_project(str(project))
    names = [p.name for p in files]
    assert 'keep.txt' in names
    assert 'ignoreme.txt' not in names
