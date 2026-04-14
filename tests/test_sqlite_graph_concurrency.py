"""Concurrency tests for the real SQLiteGraph backend.

These tests target the hostile-review finding that SQLiteGraph shares a single
sqlite3 connection across threads with check_same_thread=False. Under real load
that causes API misuse errors, transaction corruption, and dropped writes.

The fix should provide safe concurrent reads/writes with no exceptions and no
lost triples.
"""

from __future__ import annotations

import threading

from swampcastle.storage.sqlite_graph import SQLiteGraph


def test_concurrent_add_triple_and_query_entity_is_safe(tmp_path):
    """Concurrent writers/readers must not raise and must not lose writes.

    This fails against the old shared-connection implementation with errors
    like:
    - sqlite3.InterfaceError: bad parameter or other API misuse
    - sqlite3.DatabaseError: no more rows available
    - SystemError from sqlite3.Connection.__exit__
    """
    graph = SQLiteGraph(str(tmp_path / "kg.sqlite3"))
    n_threads = 8
    triples_per_thread = 40
    barrier = threading.Barrier(n_threads)
    errors: list[str] = []

    def worker(thread_id: int):
        try:
            barrier.wait()
        except threading.BrokenBarrierError as exc:  # pragma: no cover - catastrophic
            errors.append(repr(exc))
            return

        subject = f"subject_{thread_id}"
        for i in range(triples_per_thread):
            try:
                graph.add_triple(subject=subject, predicate="likes", obj=f"object_{thread_id}_{i}")
                rows = graph.query_entity(name=subject, direction="outgoing")
                # query result should be structurally sane while writes proceed
                if not isinstance(rows, list):
                    errors.append(f"unexpected query result type: {type(rows)!r}")
                    return
            except Exception as exc:  # noqa: BLE001 - this test must capture every failure
                errors.append(repr(exc))
                return

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert not errors, f"Concurrent SQLiteGraph access raised exceptions: {errors[:10]}"
        stats = graph.stats()
        expected = n_threads * triples_per_thread
        assert stats["triples"] == expected, (
            f"Lost writes under concurrency: expected {expected} triples, got {stats['triples']}"
        )
    finally:
        graph.close()


def test_concurrent_invalidate_is_safe(tmp_path):
    """Concurrent invalidations on distinct facts must complete without locking errors."""
    graph = SQLiteGraph(str(tmp_path / "kg.sqlite3"))
    n_threads = 6
    barrier = threading.Barrier(n_threads)
    errors: list[str] = []

    for i in range(n_threads):
        graph.add_triple(subject=f"A{i}", predicate="knows", obj=f"B{i}")

    def worker(i: int):
        try:
            barrier.wait()
            graph.invalidate(subject=f"A{i}", predicate="knows", obj=f"B{i}", ended="2026-06-01")
            rows = graph.query_entity(name=f"A{i}", direction="outgoing")
            assert rows[0]["valid_to"] == "2026-06-01"
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert not errors, f"Concurrent invalidate raised exceptions: {errors[:10]}"
    finally:
        graph.close()
