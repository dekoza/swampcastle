"""Coverage for python -m swampcastle entrypoint."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import patch


def test_module_entrypoint_calls_cli_main(monkeypatch):
    monkeypatch.delitem(sys.modules, "swampcastle.__main__", raising=False)
    with patch("swampcastle.cli.main") as mock_main:
        importlib.import_module("swampcastle.__main__")
    mock_main.assert_called_once()
