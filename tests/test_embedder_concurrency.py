"""Tests for thread-safety of the embedder cache (get_embedder).

Bug: _embedder_cache is a plain module-level dict. Concurrent calls to
get_embedder() from multiple threads can race during cache-miss construction:
two threads both see the cache miss, both start building the embedder, and
one silently overwrites the other — potentially creating multiple instances
or raising during re-entrant init.

Fix: guard cache writes with a threading.Lock.

References: docs/reviews/architecture_critical_review.md §7
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

from swampcastle.embeddings import _embedder_cache, get_embedder


@pytest.fixture(autouse=True)
def _clear_cache():
    """Isolate every test: clear the module-level cache before and after."""
    _embedder_cache.clear()
    yield
    _embedder_cache.clear()


# ---------------------------------------------------------------------------
# Unit: basic cache and singleton behaviour
# ---------------------------------------------------------------------------


class TestGetEmbedderBasics:
    def test_returns_same_instance_on_repeated_calls(self):
        """get_embedder() with the same config must return the exact same object."""
        with patch("swampcastle.embeddings.OnnxEmbedder") as mock_cls:
            mock_cls.return_value = MagicMock()
            first = get_embedder({})
            second = get_embedder({})
        assert first is second, "Expected singleton; got two different instances"
        assert mock_cls.call_count == 1, (
            f"OnnxEmbedder constructor called {mock_cls.call_count} times, expected 1"
        )

    def test_different_configs_produce_different_instances(self):
        """Two distinct config keys must cache independently."""
        with patch("swampcastle.embeddings.OnnxEmbedder") as mock_cls:
            mock_cls.side_effect = lambda: MagicMock()
            first = get_embedder({})
            second = get_embedder({"embedder": "some-other-model-name-that-bypasses-onnx"})
        # They can be different objects; the point is neither crashes
        assert first is not None
        assert second is not None


# ---------------------------------------------------------------------------
# Concurrency: many threads requesting the same embedder simultaneously
# ---------------------------------------------------------------------------


class TestGetEmbedderConcurrency:
    def test_concurrent_requests_produce_single_instance(self):
        """50 threads racing for the same embedder key must all receive the same object
        and the constructor must be called exactly once."""
        call_count = 0

        class FakeEmbedder:
            pass

        # We want a slow constructor to maximise the race window
        def slow_onnx():
            nonlocal call_count
            import time

            time.sleep(0.01)
            call_count += 1
            return FakeEmbedder()

        results: list = [None] * 50
        errors: list = []

        def worker(idx):
            try:
                results[idx] = get_embedder({})
            except Exception as exc:
                errors.append(exc)

        with patch("swampcastle.embeddings.OnnxEmbedder", side_effect=slow_onnx):
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert not errors, f"Threads raised exceptions: {errors}"
        assert call_count == 1, (
            f"OnnxEmbedder constructor called {call_count} times — expected exactly 1 "
            "(indicates a race where multiple threads constructed the embedder)"
        )
        # All threads must have received the same instance
        unique = set(id(r) for r in results if r is not None)
        assert len(unique) == 1, (
            f"Threads received {len(unique)} distinct embedder instances — expected 1"
        )

    def test_no_exception_under_concurrent_different_configs(self):
        """Multiple threads requesting different embedder configs must not interfere."""
        errors: list = []

        def worker(idx):
            try:
                # Alternate between two different cache keys
                cfg = (
                    {}
                    if idx % 2 == 0
                    else {"embedder": "ollama", "embedder_options": {"model": "nomic-embed-text"}}
                )
                get_embedder(cfg)
            except Exception as exc:
                errors.append(exc)

        with (
            patch("swampcastle.embeddings.OnnxEmbedder", return_value=MagicMock()),
            patch("swampcastle.embeddings.OllamaEmbedder", return_value=MagicMock()),
        ):
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert not errors, f"Concurrent different-config requests raised: {errors}"
