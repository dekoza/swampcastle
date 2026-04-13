"""Tests for swampcastle.cli — rebuilt thin dispatcher."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from swampcastle.cli.main import main


class TestNoArgs:
    def test_prints_help(self, capsys):
        with patch("sys.argv", ["swampcastle"]):
            main()
        assert "SwampCastle" in capsys.readouterr().out

    def test_help_hides_internal_and_easter_egg_commands(self, capsys):
        with patch("sys.argv", ["swampcastle", "--help"]):
            try:
                main()
            except SystemExit:
                pass

        out = capsys.readouterr().out
        assert "==SUPPRESS==" not in out
        assert "\n    hook" not in out
        assert "\n    instructions" not in out
        assert "\n    ni" not in out


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
                self.catalog = SimpleNamespace(
                    status=lambda: SimpleNamespace(total_drawers=0, wings={}, rooms={})
                )

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

    def test_rejects_unsupported_loop_flags(self):
        with patch("sys.argv", ["swampcastle", "parley", "--server", "http://x", "--auto"]):
            with pytest.raises(SystemExit):
                main()


class TestNi:
    def test_easter_egg(self, capsys):
        with patch("sys.argv", ["swampcastle", "ni"]):
            main()
        assert "Ni!" in capsys.readouterr().out


class TestHook:
    def test_requires_internal_guard(self, monkeypatch, capsys):
        monkeypatch.delenv("SWAMPCASTLE_INTERNAL", raising=False)
        with patch(
            "sys.argv", ["swampcastle", "hook", "run", "--hook", "stop", "--harness", "claude-code"]
        ):
            with pytest.raises(SystemExit, match="2"):
                main()
        assert "internal command" in capsys.readouterr().out.lower()

    def test_dispatches_with_internal_guard(self, monkeypatch):
        monkeypatch.setenv("SWAMPCASTLE_INTERNAL", "1")
        with patch(
            "sys.argv", ["swampcastle", "hook", "run", "--hook", "stop", "--harness", "claude-code"]
        ):
            with patch("swampcastle.cli.commands.cmd_hook") as mock:
                main()
                mock.assert_called_once()


class TestInstructions:
    def test_requires_internal_guard(self, monkeypatch, capsys):
        monkeypatch.delenv("SWAMPCASTLE_INTERNAL", raising=False)
        with patch("sys.argv", ["swampcastle", "instructions", "help"]):
            with pytest.raises(SystemExit, match="2"):
                main()
        assert "internal command" in capsys.readouterr().out.lower()

    def test_dispatches_with_internal_guard(self, monkeypatch):
        monkeypatch.setenv("SWAMPCASTLE_INTERNAL", "1")
        with patch("sys.argv", ["swampcastle", "instructions", "help"]):
            with patch("swampcastle.cli.commands.cmd_instructions") as mock:
                main()
                mock.assert_called_once()


class TestInternalCommandHandlers:
    def test_cmd_hook_calls_run_hook_with_fields(self):
        from swampcastle.cli.commands import cmd_hook

        args = SimpleNamespace(hook="stop", harness="claude-code")
        with patch("swampcastle.hooks_cli.run_hook") as mock:
            cmd_hook(args)

        mock.assert_called_once_with("stop", "claude-code")

    def test_cmd_instructions_calls_run_instructions_with_name(self):
        from swampcastle.cli.commands import cmd_instructions

        args = SimpleNamespace(name="help")
        with patch("swampcastle.instructions_cli.run_instructions") as mock:
            cmd_instructions(args)

        mock.assert_called_once_with("help")

    def test_cmd_raise_calls_real_migration_entrypoint(self):
        from swampcastle.cli.commands import cmd_raise

        args = SimpleNamespace(
            source_palace="/legacy/palace",
            target_castle="/new/castle",
            palace=None,
            dry_run=True,
        )
        with patch("swampcastle.migrate.migrate") as mock:
            cmd_raise(args)

        mock.assert_called_once_with(
            source_palace="/legacy/palace",
            target_castle="/new/castle",
            dry_run=True,
        )
