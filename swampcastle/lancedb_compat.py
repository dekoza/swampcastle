"""Compatibility shims for LanceDB runtime behavior.

SwampCastle uses LanceDB through its synchronous Python API. Under the hood,
LanceDB bridges into an async background event loop. If the user hits Ctrl-C
while a sync call is blocked on that bridge, the default LanceDB helper
re-raises ``KeyboardInterrupt`` immediately after cancelling the future.

That is too abrupt. Python begins interpreter shutdown while LanceDB still has
background work unwinding, which can provoke ugly PyO3 panic noise on exit.

This module patches the LanceDB bridge to drain the cancelled future briefly
before letting ``KeyboardInterrupt`` propagate.
"""

from __future__ import annotations

import asyncio
import importlib


def _run_coroutine_with_interrupt_guard(loop, future, *, cancel_timeout: float = 1.0):
    """Run a coroutine on a background loop with safer Ctrl-C handling."""
    concurrent_future = asyncio.run_coroutine_threadsafe(future, loop)
    try:
        return concurrent_future.result()
    except KeyboardInterrupt:
        concurrent_future.cancel()
        try:
            concurrent_future.result(timeout=cancel_timeout)
        except BaseException:
            pass
        raise
    except BaseException:
        concurrent_future.cancel()
        raise


def patch_lancedb_background_loop(*, cancel_timeout: float = 1.0) -> None:
    """Patch LanceDB's BackgroundEventLoop.run with Ctrl-C-safe behavior.

    The patch is idempotent and only affects the sync-to-async bridge method.
    """
    background_loop = importlib.import_module("lancedb.background_loop")
    current = background_loop.BackgroundEventLoop.run
    if getattr(current, "_swampcastle_interrupt_safe", False):
        return

    def run(self, future):
        return _run_coroutine_with_interrupt_guard(
            self.loop,
            future,
            cancel_timeout=cancel_timeout,
        )

    run._swampcastle_interrupt_safe = True
    background_loop.BackgroundEventLoop.run = run
