"""Tests for LanceDB compatibility shims."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from swampcastle.lancedb_compat import (
    _run_coroutine_with_interrupt_guard,
    patch_lancedb_background_loop,
)


class FakeConcurrentFuture:
    def __init__(self, *, second_result_exception: BaseException | None = None):
        self.cancel_called = False
        self.result_calls: list[float | None] = []
        self._second_result_exception = second_result_exception or asyncio.CancelledError()

    def result(self, timeout=None):
        self.result_calls.append(timeout)
        if len(self.result_calls) == 1:
            raise KeyboardInterrupt
        raise self._second_result_exception

    def cancel(self):
        self.cancel_called = True


def test_run_coroutine_with_interrupt_guard_cancels_and_drains(monkeypatch):
    future = FakeConcurrentFuture()
    seen = {"future": None, "loop": None}

    def fake_submit(coro, loop):
        seen["future"] = coro
        seen["loop"] = loop
        return future

    monkeypatch.setattr(
        "swampcastle.lancedb_compat.asyncio.run_coroutine_threadsafe",
        fake_submit,
    )

    with pytest.raises(KeyboardInterrupt):
        _run_coroutine_with_interrupt_guard(object(), object(), cancel_timeout=0.25)

    assert future.cancel_called is True
    assert future.result_calls == [None, 0.25]
    assert seen["loop"] is not None


def test_patch_lancedb_background_loop_is_idempotent(monkeypatch):
    def original_run(self, future):
        return None

    fake_bg = SimpleNamespace(
        BackgroundEventLoop=SimpleNamespace(run=original_run),
    )

    monkeypatch.setattr(
        "swampcastle.lancedb_compat.importlib.import_module",
        lambda name: fake_bg,
    )

    patch_lancedb_background_loop()
    first = fake_bg.BackgroundEventLoop.run
    assert getattr(first, "_swampcastle_interrupt_safe", False) is True

    patch_lancedb_background_loop()
    assert fake_bg.BackgroundEventLoop.run is first
