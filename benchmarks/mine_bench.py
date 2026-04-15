from __future__ import annotations

import argparse
import json

from swampcastle.parallel_benchmarks import format_benchmark_report, run_mine_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark spawn-based mine() fairly with fresh storage, alternating order, "
            "and sequential/parallel parity checks."
        )
    )
    parser.add_argument("--files", type=int, default=300, help="Number of synthetic project files")
    parser.add_argument(
        "--lines-per-file", type=int, default=80, help="Repeated lines written to each file"
    )
    parser.add_argument("-w", type=int, default=4, help="Parallel worker count")
    parser.add_argument("--runs", type=int, default=5, help="Measured run pairs")
    parser.add_argument("--warmup", type=int, default=1, help="Warmup run pairs")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args()

    report = run_mine_benchmark(
        file_count=args.files,
        lines_per_file=args.lines_per_file,
        workers=args.w,
        runs=args.runs,
        warmup=args.warmup,
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    print(format_benchmark_report(report))


if __name__ == "__main__":
    main()
