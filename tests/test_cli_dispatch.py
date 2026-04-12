"""Tests for swampcastle.cli — rebuilt thin dispatcher."""

import sys
from unittest.mock import patch

import pytest


class TestDispatch:
    def test_no_args_prints_help(self, capsys):
        with patch("sys.argv", ["swampcastle"]):
            from swampcastle.cli.main import main
            main()
        assert "SwampCastle" in capsys.readouterr().out

    def test_survey_dispatches(self, capsys):
        with patch("sys.argv", ["swampcastle", "survey"]):
            from swampcastle.cli.main import main
            main()
        out = capsys.readouterr().out
        assert "drawers" in out.lower() or "castle" in out.lower()

    def test_drawbridge_no_subcommand_shows_setup(self, capsys):
        with patch("sys.argv", ["swampcastle", "drawbridge"]):
            from swampcastle.cli.main import main
            main()
        out = capsys.readouterr().out
        assert "swampcastle drawbridge run" in out

    def test_drawbridge_run_starts_mcp(self):
        with patch("sys.argv", ["swampcastle", "drawbridge", "run"]):
            with patch("swampcastle.mcp.server.main") as mock_main:
                from swampcastle.cli.main import main
                main()
                mock_main.assert_called_once()

    def test_unknown_command_exits(self, capsys):
        with patch("sys.argv", ["swampcastle", "bogus"]):
            from swampcastle.cli.main import main
            with pytest.raises(SystemExit):
                main()
