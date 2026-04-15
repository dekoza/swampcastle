"""Helpers for reproducible sequential vs parallel maintenance benchmarks."""

from __future__ import annotations

import io
import json
import statistics
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from time import perf_counter

import yaml

from swampcastle.mining.miner import mine
from swampcastle.models.drawer import AddDrawerCommand
from swampcastle.services.vault import VaultService
from swampcastle.storage.memory import InMemoryStorageFactory
from swampcastle.wal import WalWriter


def summarize_timings(samples: list[float]) -> dict[str, float | int]:
    if not samples:
        raise ValueError("samples must not be empty")

    stdev = statistics.stdev(samples) if len(samples) > 1 else 0.0
    return {
        "samples": len(samples),
        "min_seconds": min(samples),
        "max_seconds": max(samples),
        "mean_seconds": statistics.mean(samples),
        "median_seconds": statistics.median(samples),
        "stdev_seconds": stdev,
    }


def alternating_case_order(run_index: int) -> tuple[str, str]:
    if run_index % 2 == 0:
        return ("sequential", "parallel")
    return ("parallel", "sequential")


def _build_distill_vault(root: Path, *, drawer_count: int, multiplier: int) -> VaultService:
    factory = InMemoryStorageFactory()
    wal = WalWriter(root / "wal")
    vault = VaultService(factory.open_collection("swampcastle_chests"), wal)

    for index in range(drawer_count):
        content = (
            f"Document {index} discusses architecture, testing, and performance. " * multiplier
        )
        vault.add_drawer(
            AddDrawerCommand(
                wing="bench",
                room="r1",
                content=content,
                source_file=f"doc_{index}.md",
            )
        )

    return vault


def _collect_aaak(vault: VaultService) -> dict[str, str]:
    rows = vault.get_drawers(include=["metadatas"])
    return {doc_id: metadata["aaak"] for doc_id, metadata in zip(rows["ids"], rows["metadatas"])}


def _run_distill_case(case: str, *, drawer_count: int, multiplier: int, workers: int) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = _build_distill_vault(Path(tmpdir), drawer_count=drawer_count, multiplier=multiplier)
        started = perf_counter()
        if case == "sequential":
            count = vault.distill()
        else:
            count = vault.distill(parallel_workers=workers)
        elapsed = perf_counter() - started
        return {
            "case": case,
            "seconds": elapsed,
            "count": count,
            "aaak": _collect_aaak(vault),
        }


def run_distill_benchmark(
    *,
    n: int = 1000,
    mult: int = 500,
    workers: int = 4,
    runs: int = 5,
    warmup: int = 1,
) -> dict:
    sequential_samples: list[float] = []
    parallel_samples: list[float] = []
    orders: list[list[str]] = []

    for run_index in range(warmup + runs):
        order = alternating_case_order(run_index)
        pair_results = {}
        for case in order:
            result = _run_distill_case(
                case,
                drawer_count=n,
                multiplier=mult,
                workers=workers,
            )
            pair_results[case] = result

        if pair_results["sequential"]["count"] != pair_results["parallel"]["count"]:
            raise AssertionError("distill benchmark count mismatch between sequential and parallel")
        if pair_results["sequential"]["aaak"] != pair_results["parallel"]["aaak"]:
            raise AssertionError("distill benchmark AAAK mismatch between sequential and parallel")

        if run_index >= warmup:
            sequential_samples.append(pair_results["sequential"]["seconds"])
            parallel_samples.append(pair_results["parallel"]["seconds"])
            orders.append(list(order))

    sequential = summarize_timings(sequential_samples)
    parallel = summarize_timings(parallel_samples)
    speedup = sequential["mean_seconds"] / parallel["mean_seconds"]

    return {
        "benchmark": "distill",
        "drawers": n,
        "multiplier": mult,
        "workers": workers,
        "runs": runs,
        "warmup": warmup,
        "orders": orders,
        "parity_ok": True,
        "sequential": sequential,
        "parallel": parallel,
        "speedup_vs_sequential": speedup,
    }


def _write_benchmark_project(project_root: Path, *, file_count: int, lines_per_file: int) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "sub").mkdir(exist_ok=True)

    config = {
        "wing": "bench_project",
        "rooms": [
            {"name": "code", "description": "Source code", "keywords": ["def", "class"]},
            {"name": "docs", "description": "Documentation", "keywords": ["notes", "readme"]},
            {"name": "general", "description": "General"},
        ],
    }
    (project_root / ".swampcastle.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")

    suffix_cycle = [".py", ".md", ".txt"]
    for index in range(file_count):
        suffix = suffix_cycle[index % len(suffix_cycle)]
        directory = project_root if index % 2 == 0 else project_root / "sub"
        path = directory / f"file_{index}{suffix}"
        if suffix == ".py":
            line = f"def function_{index}():\n    return {index}\n"
        elif suffix == ".md":
            line = f"# Notes {index}\n\nThis file documents architecture and testing.\n"
        else:
            line = f"General text {index} about rooms, drawers, and storage.\n"
        path.write_text(line * lines_per_file, encoding="utf-8")


def _run_mine_case(case: str, *, project_root: Path, workers: int) -> dict:
    factory = InMemoryStorageFactory()
    palace_path = project_root / f"palace_{case}"
    started = perf_counter()
    with redirect_stdout(io.StringIO()):
        if case == "sequential":
            mine(str(project_root), str(palace_path), storage_factory=factory)
        else:
            mine(
                str(project_root),
                str(palace_path),
                storage_factory=factory,
                parallel_workers=workers,
            )
    elapsed = perf_counter() - started

    collection = factory.open_collection("swampcastle_chests")
    rows = collection.get(include=["metadatas"])
    signature = sorted(rows["ids"])
    return {
        "case": case,
        "seconds": elapsed,
        "drawer_count": collection.count(),
        "signature": signature,
    }


def run_mine_benchmark(
    *,
    file_count: int = 300,
    lines_per_file: int = 80,
    workers: int = 4,
    runs: int = 5,
    warmup: int = 1,
) -> dict:
    sequential_samples: list[float] = []
    parallel_samples: list[float] = []
    orders: list[list[str]] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        project_root = root / "project"
        _write_benchmark_project(project_root, file_count=file_count, lines_per_file=lines_per_file)

        for run_index in range(warmup + runs):
            order = alternating_case_order(run_index)
            pair_results = {}
            for case in order:
                pair_results[case] = _run_mine_case(
                    case, project_root=project_root, workers=workers
                )

            if (
                pair_results["sequential"]["drawer_count"]
                != pair_results["parallel"]["drawer_count"]
            ):
                raise AssertionError(
                    "mine benchmark drawer count mismatch between sequential and parallel"
                )
            if pair_results["sequential"]["signature"] != pair_results["parallel"]["signature"]:
                raise AssertionError("mine benchmark drawer signature mismatch")

            if run_index >= warmup:
                sequential_samples.append(pair_results["sequential"]["seconds"])
                parallel_samples.append(pair_results["parallel"]["seconds"])
                orders.append(list(order))

    sequential = summarize_timings(sequential_samples)
    parallel = summarize_timings(parallel_samples)
    speedup = sequential["mean_seconds"] / parallel["mean_seconds"]

    return {
        "benchmark": "mine",
        "files": file_count,
        "lines_per_file": lines_per_file,
        "workers": workers,
        "runs": runs,
        "warmup": warmup,
        "orders": orders,
        "parity_ok": True,
        "drawer_count": pair_results["sequential"]["drawer_count"],
        "sequential": sequential,
        "parallel": parallel,
        "speedup_vs_sequential": speedup,
    }


def format_benchmark_report(report: dict) -> str:
    sequential = report["sequential"]
    parallel = report["parallel"]
    lines = [
        f"Benchmark: {report['benchmark']}",
        f"Runs: {report['runs']}  Warmup: {report['warmup']}  Workers: {report['workers']}",
        f"Parity OK: {report['parity_ok']}",
        "",
        "Sequential:",
        json.dumps(sequential, indent=2, sort_keys=True),
        "",
        "Parallel:",
        json.dumps(parallel, indent=2, sort_keys=True),
        "",
        f"Speedup vs sequential: {report['speedup_vs_sequential']:.2f}x",
    ]
    return "\n".join(lines)
