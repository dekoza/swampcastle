from swampcastle.parallel_benchmarks import (
    alternating_case_order,
    run_distill_benchmark,
    run_mine_benchmark,
    summarize_timings,
)


def test_summarize_timings_single_sample_has_zero_stdev():
    summary = summarize_timings([0.25])

    assert summary["samples"] == 1
    assert summary["mean_seconds"] == 0.25
    assert summary["stdev_seconds"] == 0.0


def test_alternating_case_order_flips_each_run():
    assert alternating_case_order(0) == ("sequential", "parallel")
    assert alternating_case_order(1) == ("parallel", "sequential")
    assert alternating_case_order(2) == ("sequential", "parallel")


def test_run_distill_benchmark_reports_parity():
    report = run_distill_benchmark(n=6, mult=8, workers=2, runs=1, warmup=0)

    assert report["parity_ok"] is True
    assert report["drawers"] == 6
    assert report["orders"] == [["sequential", "parallel"]]
    assert report["sequential"]["samples"] == 1
    assert report["parallel"]["samples"] == 1
    assert report["sequential"]["mean_seconds"] > 0
    assert report["parallel"]["mean_seconds"] > 0


def test_run_mine_benchmark_reports_parity():
    report = run_mine_benchmark(file_count=6, lines_per_file=12, workers=2, runs=1, warmup=0)

    assert report["parity_ok"] is True
    assert report["files"] == 6
    assert report["orders"] == [["sequential", "parallel"]]
    assert report["drawer_count"] > 0
    assert report["sequential"]["samples"] == 1
    assert report["parallel"]["samples"] == 1
    assert report["sequential"]["mean_seconds"] > 0
    assert report["parallel"]["mean_seconds"] > 0
