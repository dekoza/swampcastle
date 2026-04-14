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
    """Isolate every test: clear the module-level cache before and after.

    The clear itself is protected by the module lock so it is safe even if
    tests were ever run in parallel (e.g. pytest-xdist).
    """
    from swampcastle.embeddings import _embedder_lock

    with _embedder_lock:
        _embedder_cache.clear()
    yield
    with _embedder_lock:
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
        """Two distinct config keys must cache and return independently."""
        with (
            patch("swampcastle.embeddings.OnnxEmbedder", return_value=MagicMock()),
            patch("swampcastle.embeddings.OllamaEmbedder", return_value=MagicMock()),
        ):
            first = get_embedder({})
            second = get_embedder({"embedder": "ollama"})
        assert first is not None
        assert second is not None
        assert first is not second, "Different config keys must return distinct cached instances"


# ---------------------------------------------------------------------------
# Concurrency: many threads requesting the same embedder simultaneously
# ---------------------------------------------------------------------------


class TestGetEmbedderConcurrency:
    def test_concurrent_requests_produce_single_instance(self):
        """50 threads racing for the same embedder key must all receive the same object
        and the constructor must be called exactly once.

        A threading.Barrier synchronises all threads before they call get_embedder
        so they all hit the cache-miss path simultaneously — making the race
        deterministic rather than relying on OS scheduling and sleep().
        """
        call_count = 0
        n_threads = 50
        barrier = threading.Barrier(n_threads)

        class FakeEmbedder:
            pass

        def slow_onnx():
            nonlocal call_count
            call_count += 1
            return FakeEmbedder()

        results: list = [None] * n_threads
        errors: list = []

        def worker(idx):
            try:
                barrier.wait()  # all threads start simultaneously
                results[idx] = get_embedder({})
            except Exception as exc:
                errors.append(exc)

        with patch("swampcastle.embeddings.OnnxEmbedder", side_effect=slow_onnx):
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert not errors, f"Threads raised exceptions: {errors}"
        assert call_count == 1, (
            f"OnnxEmbedder constructor called {call_count} times — expected exactly 1 "
            "(indicates a race where multiple threads constructed the embedder)"
        )
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
