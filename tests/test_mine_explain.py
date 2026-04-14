import sys
from pathlib import Path
from swampcastle.mining.miner import mine


def make_project(dirpath: Path):
    # write minimal .swampcastle.yaml
    cfg = {
        'wing': 'test',
        'rooms': [{'name': 'general', 'description': 'All files'}]
    }
    import yaml

    (dirpath / '.swampcastle.yaml').write_text(yaml.dump(cfg))


def test_mine_explain_prints_skip_reason(tmp_path, capsys):
    project = tmp_path
    make_project(project)
    # create a minified-looking file
    f = project / 'app.min.js'
    f.write_text('var a=0;')

    # run mine in dry-run with explain=True
    mine(str(project), str(project / 'palace'), dry_run=True, explain=True)

    out = capsys.readouterr().out
    assert 'SKIP' in out or 'skip' in out
    assert 'app.min.js' in out
