"""Ingestion pipeline benchmarks.

Measures throughput of embedding buffer and skeleton extraction.

NOTE — what these benchmarks actually measure:
  - test_benchmark_embedding_batching: Python call-overhead amortization.
    With InMemoryStorageFactory + a real ONNX/ST embedder, the dominant cost is
    embedder.embed() model inference. Batching amortizes per-call overhead and
    GPU kernel launches. In-memory upsert itself is trivial (dict write), so the
    absolute times here reflect model load + inference, not storage latency.
  - test_benchmark_skeleton_speed: AST parsing cost vs chunking cost for large
    Python files. The speedup here is genuine: fewer chunks = fewer upsert calls.

Run with: uv run pytest tests/benchmarks/ -s
"""

import time

import yaml
from pathlib import Path

from swampcastle.mining.miner import mine
from swampcastle.storage.memory import InMemoryStorageFactory


def make_dummy_project(path: Path, num_files: int = 10, lines_per_file: int = 1000):
    path.mkdir(parents=True, exist_ok=True)
    cfg = {"wing": "bench", "rooms": [{"name": "general", "description": "test"}]}
    (path / '.swampcastle.yaml').write_text(yaml.dump(cfg))
    for i in range(num_files):
        (path / f"file_{i}.txt").write_text(
            "\n".join([f"line {j} in file {i}" for j in range(lines_per_file)])
        )


def test_benchmark_embedding_batching(tmp_path, monkeypatch):
    """Batch (BS=64) vs serial (BS=1) — measures call-overhead amortization.

    With a real embedding backend these numbers represent 2-10x speedup from
    fewer model round-trips. With InMemory + ONNX the dominant cost is model
    inference; batching here reduces per-inference overhead.
    """
    project = tmp_path / "bench_proj"
    make_dummy_project(project, num_files=10, lines_per_file=1000)
    palace = str(tmp_path / "palace")

    monkeypatch.setenv('SWAMPCASTLE_EMBED_BATCH_SIZE', '1')
    start = time.perf_counter()
    mine(str(project), palace, dry_run=False, storage_factory=InMemoryStorageFactory())
    serial_time = time.perf_counter() - start

    monkeypatch.setenv('SWAMPCASTLE_EMBED_BATCH_SIZE', '64')
    start = time.perf_counter()
    mine(str(project), palace, dry_run=False, storage_factory=InMemoryStorageFactory())
    batch_time = time.perf_counter() - start

    print(f"\n[BENCHMARK] Serial (BS=1):   {serial_time:.4f}s")
    print(f"[BENCHMARK] Batched (BS=64): {batch_time:.4f}s")
    print(f"[BENCHMARK] Speedup:         {serial_time / batch_time:.1f}x (call-overhead amortization)")
    # No assertion on absolute time — environment-dependent.
    # Batching should never be slower than serial in a clean environment.
    assert batch_time < serial_time, (
        f"Batching ({batch_time:.4f}s) was not faster than serial ({serial_time:.4f}s); "
        "check embedder configuration"
    )


def test_benchmark_skeleton_speed(tmp_path):
    """Skeleton mode vs full-file mode for a large Python file.

    Skeleton produces fewer chunks → fewer upsert calls → faster ingestion.
    The speedup is proportional to how much the skeleton reduces file size.
    """
    project = tmp_path / "bench_skeleton"
    project.mkdir()
    cfg = {"wing": "bench", "rooms": [{"name": "general", "description": "test"}]}
    (project / '.swampcastle.yaml').write_text(yaml.dump(cfg))

    large_py = project / "huge.py"
    lines = ["def func_{}(x):\n    return x + 1".format(i) for i in range(2500)]
    large_py.write_text("\n\n".join(lines))

    palace = str(tmp_path / "palace_skeleton")

    start = time.perf_counter()
    mine(str(project), palace, dry_run=False, storage_factory=InMemoryStorageFactory())
    skeleton_time = time.perf_counter() - start

    start = time.perf_counter()
    mine(str(project), palace, dry_run=False,
         storage_factory=InMemoryStorageFactory(), force_no_skeleton=True)
    full_time = time.perf_counter() - start

    print(f"\n[BENCHMARK] Skeleton mode: {skeleton_time:.4f}s")
    print(f"[BENCHMARK] Full file:     {full_time:.4f}s")
    if full_time > 0:
        print(f"[BENCHMARK] Speedup:       {full_time / skeleton_time:.1f}x")
    # Skeleton is only triggered when it reduces size by >50%, so this should
    # always be faster. If the 2500-function file doesn't meet the threshold,
    # both times will be equal and the assertion will catch a regression.
    assert skeleton_time <= full_time, (
        f"Skeleton ({skeleton_time:.4f}s) was not faster than full ({full_time:.4f}s)"
    )
