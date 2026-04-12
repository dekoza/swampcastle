import os
import json
import tempfile
from swampcastle.config import CastleConfig


def test_default_config():
    cfg = CastleConfig(config_dir=tempfile.mkdtemp())
    assert "castle" in cfg.palace_path
    assert cfg.collection_name == "swampcastle_chests"


def test_config_from_file():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"palace_path": "/custom/palace"}, f)
    cfg = CastleConfig(config_dir=tmpdir)
    assert cfg.palace_path == "/custom/palace"


def test_env_override_new():
    os.environ["SWAMPCASTLE_PATH"] = "/env/castle"
    cfg = CastleConfig(config_dir=tempfile.mkdtemp())
    assert cfg.palace_path == "/env/castle"
    del os.environ["SWAMPCASTLE_PATH"]


def test_env_override_legacy():
    os.environ["MEMPALACE_PALACE_PATH"] = "/env/legacy"
    cfg = CastleConfig(config_dir=tempfile.mkdtemp())
    assert cfg.palace_path == "/env/legacy"
    del os.environ["MEMPALACE_PALACE_PATH"]


def test_init():
    tmpdir = tempfile.mkdtemp()
    cfg = CastleConfig(config_dir=tmpdir)
    cfg.init()
    assert os.path.exists(os.path.join(tmpdir, "config.json"))
