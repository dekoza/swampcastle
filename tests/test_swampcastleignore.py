from pathlib import Path

from swampcastle.mining.miner import scan_project


def test_swampcastleignore_excludes_file(tmp_path):
    project = tmp_path
    # create files
    f1 = project / 'keep.txt'
    f1.write_text('hello')
    f2 = project / 'ignoreme.txt'
    f2.write_text('secret')
    # create .swampcastleignore to exclude ignoreme.txt
    (project / '.swampcastleignore').write_text('ignoreme.txt\n')

    files = scan_project(str(project))
    paths = [p.name for p in files]
    assert 'keep.txt' in paths
    assert 'ignoreme.txt' not in paths


def test_swampcastleignore_respects_force_include(tmp_path):
    project = tmp_path
    f = project / 'ignoreme.txt'
    f.write_text('secret')
    (project / '.swampcastleignore').write_text('ignoreme.txt\n')

    # force include the file by relative path
    files = scan_project(str(project), include_ignored=['ignoreme.txt'])
    paths = [p.name for p in files]
    assert 'ignoreme.txt' in paths


def test_nested_swampcastleignore(tmp_path):
    project = tmp_path
    sub = project / 'pkg'
    sub.mkdir()
    keep = sub / 'keep.js'
    keep.write_text('var a=1;')
    ign = sub / 'node_modules'
    ign.mkdir()
    bad = ign / 'vendor.js'
    bad.write_text('var b=2;')
    # put .swampcastleignore in pkg to ignore node_modules/**
    (sub / '.swampcastleignore').write_text('node_modules/\n')

    files = scan_project(str(project))
    names = [p.relative_to(project).as_posix() for p in files]
    assert 'pkg/keep.js' in names
    assert 'pkg/node_modules/vendor.js' not in names
