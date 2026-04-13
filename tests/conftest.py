"""
conftest.py — Shared fixtures for SwampCastle tests.

Isolates HOME to a temp dir before any swampcastle imports — so that
module-level initialisations use the isolated environment.
"""

import os
import shutil
import tempfile

# ── Isolate HOME before any swampcastle imports ──────────────────────────
_original_env = {}
_session_tmp = tempfile.mkdtemp(prefix="swampcastle_session_")

for _var in ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH"):
    _original_env[_var] = os.environ.get(_var)

os.environ["HOME"] = _session_tmp
os.environ["USERPROFILE"] = _session_tmp
os.environ["HOMEDRIVE"] = os.path.splitdrive(_session_tmp)[0] or "C:"
os.environ["HOMEPATH"] = os.path.splitdrive(_session_tmp)[1] or _session_tmp

import pytest  # noqa: E402

from swampcastle.settings import CastleSettings  # noqa: E402
from swampcastle.storage.memory import InMemoryStorageFactory  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _isolate_home():
    """
    Session-scoped fixture that sets HOME to a temp dir.

    The env vars were already set at module level (above) so that
    module-level initialisations are captured. This fixture simply
    restores the originals on teardown and cleans up the temp dir.
    """
    yield
    for var, orig in _original_env.items():
        if orig is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = orig
    shutil.rmtree(_session_tmp, ignore_errors=True)


@pytest.fixture
def tmp_dir(tmp_path):
    """A temp directory for test artifacts."""
    return str(tmp_path)


@pytest.fixture
def castle_settings(tmp_path):
    """CastleSettings pointing at a temp castle."""
    return CastleSettings(castle_path=tmp_path / "castle", _env_file=None)


@pytest.fixture
def memory_factory():
    """InMemoryStorageFactory for unit tests."""
    return InMemoryStorageFactory()
