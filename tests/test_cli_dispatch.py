"""Tests for swampcastle.cli — rebuilt thin dispatcher."""

from types import SimpleNamespace
from unittest.mock import patch

from swampcastle.cli.main import main


class TestNoArgs:
    def test_prints_help(self, capsys):
        with patch("sys.argv", ["swampcastle"]):
            main()
        assert "SwampCastle" in capsys.readouterr().out


class TestSurvey:
    def test_dispatches(self, capsys):
        with patch("sys.argv", ["swampcastle", "survey"]):
            main()
        assert "drawers" in capsys.readouterr().out.lower()

    def test_status_alias(self, capsys):
        with patch("sys.argv", ["swampcastle", "status"]):
            main()
        assert "drawers" in capsys.readouterr().out.lower()

    def test_backend_flag_passed_to_settings(self):
        class DummyCastle:
            def __init__(self, settings, factory):
                self.catalog = SimpleNamespace(status=lambda: SimpleNamespace(
                    total_drawers=0, wings={}, rooms={}
                ))

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

        with patch("sys.argv", ["swampcastle", "--backend", "postgres", "survey"]):
            with patch("swampcastle.cli.commands.CastleSettings") as mock_settings:
                mock_settings.return_value = SimpleNamespace(
                    castle_path="/tmp/castle",
                    backend="postgres",
                )
                with patch("swampcastle.cli.commands.factory_from_settings", return_value=object()):
                    with patch("swampcastle.castle.Castle", DummyCastle):
                        main()

        assert mock_settings.call_args.kwargs["backend"] == "postgres"


class TestSeek:
    def test_no_results(self, capsys):
        with patch("sys.argv", ["swampcastle", "seek", "nonexistent"]):
            main()
        assert "no results" in capsys.readouterr().out.lower()

    def test_search_alias(self, capsys):
        with patch("sys.argv", ["swampcastle", "search", "anything"]):
            main()
        out = capsys.readouterr().out.lower()
        assert "no results" in out or "result" in out


class TestDrawbridge:
    def test_no_subcommand_shows_setup(self, capsys):
        with patch("sys.argv", ["swampcastle", "drawbridge"]):
            main()
        assert "swampcastle drawbridge run" in capsys.readouterr().out

    def test_mcp_alias(self, capsys):
        with patch("sys.argv", ["swampcastle", "mcp"]):
            main()
        assert "swampcastle drawbridge run" in capsys.readouterr().out

    def test_run_starts_mcp(self):
        with patch("sys.argv", ["swampcastle", "drawbridge", "run"]):
            with patch("swampcastle.mcp.server.main") as mock:
                main()
                mock.assert_called_once()


class TestBuild:
    def test_dispatches(self, tmp_path):
        target = tmp_path / "project"
        target.mkdir()
        (target / "README.md").write_text("# Test")
        with patch("sys.argv", ["swampcastle", "build", str(target)]):
            with patch("swampcastle.cli.commands.cmd_build") as mock:
                main()
                mock.assert_called_once()


class TestGather:
    def test_dispatches(self, tmp_path):
        target = tmp_path / "project"
        target.mkdir()
        with patch("sys.argv", ["swampcastle", "gather", str(target)]):
            with patch("swampcastle.cli.commands.cmd_gather") as mock:
                main()
                mock.assert_called_once()


class TestCleave:
    def test_dispatches(self, tmp_path):
        with patch("sys.argv", ["swampcastle", "cleave", str(tmp_path)]):
            with patch("swampcastle.cli.commands.cmd_cleave") as mock:
                main()
                mock.assert_called_once()


class TestHerald:
    def test_dispatches(self):
        with patch("sys.argv", ["swampcastle", "herald"]):
            with patch("swampcastle.cli.commands.cmd_herald") as mock:
                main()
                mock.assert_called_once()


class TestGarrison:
    def test_dispatches(self):
        with patch("sys.argv", ["swampcastle", "garrison"]):
            with patch("swampcastle.cli.commands.cmd_garrison") as mock:
                main()
                mock.assert_called_once()


class TestParley:
    def test_dispatches(self):
        with patch("sys.argv", ["swampcastle", "parley", "--server", "http://x"]):
            with patch("swampcastle.cli.commands.cmd_parley") as mock:
                main()
                mock.assert_called_once()


class TestNi:
    def test_easter_egg(self, capsys):
        with patch("sys.argv", ["swampcastle", "ni"]):
            main()
        assert "Ni!" in capsys.readouterr().out


class TestHook:
    def test_dispatches(self):
        with patch("sys.argv", ["swampcastle", "hook", "run", "--hook", "stop", "--harness", "claude-code"]):
            with patch("swampcastle.cli.commands.cmd_hook") as mock:
                main()
                mock.assert_called_once()


class TestInstructions:
    def test_dispatches(self):
        with patch("sys.argv", ["swampcastle", "instructions", "help"]):
            with patch("swampcastle.cli.commands.cmd_instructions") as mock:
                main()
                mock.assert_called_once()
