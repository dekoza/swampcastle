"""Tests for the venv-swap deploy hardening (#29).

pipx reinstall deletes and recreates the venv under a live MCP server;
already-imported modules keep working (deleted-inode mappings), but any
import still pending resolves against the mismatched new tree and throws.
The fix: resolve every write-path import at server startup.
"""

import subprocess
import sys
import textwrap

from swampcastle.mcp.server import WRITE_PATH_MODULES, preload_write_path


class TestPreloadWritePath:
    def test_write_path_modules_are_lazy_and_preload_resolves_them(self):
        """In a fresh interpreter, importing the server must NOT pull the
        write-path modules (they're lazy — that's the hazard), and
        preload_write_path() must resolve every one of them."""
        script = textwrap.dedent(
            """
            import sys
            from swampcastle.mcp.server import WRITE_PATH_MODULES, preload_write_path

            lazy = [m for m in WRITE_PATH_MODULES if m not in sys.modules]
            assert lazy, "nothing lazy left — the module list is stale, prune it"

            failures = preload_write_path()
            assert failures == [], f"preload failed for: {failures}"

            missing = [m for m in WRITE_PATH_MODULES if m not in sys.modules]
            assert missing == [], f"still unimported after preload: {missing}"

            print("LAZY_BEFORE=" + ",".join(lazy))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, result.stderr
        # The embedder's native tree — lazy until first embed — must be among
        # the genuinely-lazy set this test exercises
        lazy_before = result.stdout.strip().split("LAZY_BEFORE=")[1].split(",")
        assert "onnxruntime" in lazy_before

    def test_preload_reports_missing_modules_instead_of_raising(self):
        failures = preload_write_path(extra_modules=["definitely_not_a_module_xyz"])
        assert any(f.startswith("definitely_not_a_module_xyz:") for f in failures)

    def test_preload_warms_the_castle_embedder(self):
        class SpyEmbedder:
            def __init__(self):
                self.calls = []

            def embed(self, texts):
                self.calls.append(texts)
                return [[0.0]]

        class FakeCollection:
            def __init__(self):
                self._embedder = SpyEmbedder()

        class FakeCastle:
            def __init__(self):
                self._collection = FakeCollection()

        castle = FakeCastle()
        failures = preload_write_path(castle=castle)

        assert failures == []
        assert castle._collection._embedder.calls == [["warmup"]]

    def test_preload_skips_collections_without_embedder(self):
        class BareCastle:
            def __init__(self):
                self._collection = object()

        assert preload_write_path(castle=BareCastle()) == []

    def test_main_preloads_in_background_thread(self, monkeypatch):
        """Server startup must kick off the preload without blocking the
        stdin loop — a slow ONNX load can't delay `initialize`."""
        import io
        import threading

        from swampcastle.mcp import server

        preloaded = {}
        done = threading.Event()

        class DummyCastle:
            def __init__(self, settings, factory):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

        def spy_preload(castle=None, extra_modules=None):
            preloaded["castle"] = castle
            preloaded["thread"] = threading.current_thread()
            done.set()
            return []

        monkeypatch.setattr(server, "Castle", DummyCastle)
        monkeypatch.setattr(server, "create_handler", lambda castle: lambda request: None)
        monkeypatch.setattr(server, "preload_write_path", spy_preload)
        monkeypatch.setattr(
            "swampcastle.storage.factory_from_settings", lambda settings: object()
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(""))

        server.main()

        assert done.wait(timeout=5), "preload never ran"
        assert isinstance(preloaded["castle"], DummyCastle)
        assert preloaded["thread"] is not threading.main_thread()
        assert preloaded["thread"].daemon

    def test_embedder_warm_failure_is_reported_not_raised(self):
        class BrokenEmbedder:
            def embed(self, texts):
                raise RuntimeError("model file gone")

        class FakeCollection:
            def __init__(self):
                self._embedder = BrokenEmbedder()

        class FakeCastle:
            def __init__(self):
                self._collection = FakeCollection()

        failures = preload_write_path(castle=FakeCastle())
        assert any("embedder" in f for f in failures)
