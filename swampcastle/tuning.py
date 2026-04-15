"""Runtime performance tuning helpers.

These helpers deliberately tune throughput without changing the embedding
contract. Thread counts and mining batch sizes are operational knobs, not part
of the embedder fingerprint.
"""

from __future__ import annotations

import os


def detect_total_memory_bytes() -> int | None:
    """Best-effort physical memory detection."""
    try:
        import psutil
    except ImportError:
        psutil = None

    if psutil is not None:
        try:
            return int(psutil.virtual_memory().total)
        except Exception:
            pass

    if hasattr(os, "sysconf"):
        try:
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            phys_pages = int(os.sysconf("SC_PHYS_PAGES"))
        except (AttributeError, OSError, TypeError, ValueError):
            return None
        if page_size > 0 and phys_pages > 0:
            return page_size * phys_pages

    return None


def detect_machine_resources() -> tuple[int, int | None]:
    """Return logical CPU count and total physical memory bytes."""
    cpu_count = max(1, int(os.cpu_count() or 1))
    return cpu_count, detect_total_memory_bytes()


def suggest_onnx_tuning(
    cpu_count: int | None = None,
    total_memory_bytes: int | None = None,
) -> dict[str, int]:
    """Suggest safe ONNX CPU tuning values for the current machine.

    Heuristics intentionally bias toward stable, sync-safe defaults rather than
    absolute maximum throughput. The values should be good enough out of the
    box and serve as a starting point for optional benchmarking.
    """
    resolved_cpu = max(1, int(cpu_count or (os.cpu_count() or 1)))
    resolved_memory = total_memory_bytes if total_memory_bytes and total_memory_bytes > 0 else None
    if resolved_memory is None:
        resolved_memory = detect_total_memory_bytes()

    memory_gib = int(resolved_memory // (1024**3)) if resolved_memory else None

    intra_by_cpu = max(1, resolved_cpu // 2)
    if memory_gib is None:
        intra_threads = min(16, intra_by_cpu)
    else:
        intra_threads = min(16, intra_by_cpu, max(1, memory_gib))

    inter_threads = 1

    if memory_gib is not None and memory_gib < 8:
        embed_batch_size = 64
    elif memory_gib is not None and memory_gib < 16:
        embed_batch_size = 128
    else:
        embed_batch_size = min(256, max(64, intra_threads * 16))

    return {
        "onnx_intra_op_threads": intra_threads,
        "onnx_inter_op_threads": inter_threads,
        "embed_batch_size": embed_batch_size,
    }
