"""Measure end-to-end write/read efficiency at several publication rates.

This is intentionally a small, dependency-light benchmark rather than a
pytest test. It keeps one writer and one callback reader in the same process,
which makes ``process_time`` a useful combined CPU measure for the complete
Python API path. Run it on an otherwise idle machine for comparable results.
"""

import argparse
import time

import numpy as np

import global_buffer as gb


def run_rate(rate, duration, capacity, elements):
    name = f"gb_bench_{time.time_ns()}"
    writer = gb.create(
        name, gb.ArraySpec("float32", (elements,)), capacity=capacity
    )
    reader = gb.attach(name)
    delivered = 0

    def on_data(_sample, _seq):
        nonlocal delivered
        delivered += 1

    handle = reader.on_data(on_data, mode="next")
    frame = np.zeros(elements, dtype=np.float32)
    period = 1.0 / rate
    written = 0
    time.sleep(0.05)  # let the callback thread reach its wait loop

    cpu_start = time.process_time()
    wall_start = time.perf_counter()
    deadline = wall_start + duration
    next_write = wall_start
    while next_write < deadline:
        now = time.perf_counter()
        if now < next_write:
            time.sleep(next_write - now)
        if time.perf_counter() >= deadline:
            break
        writer.write(frame)
        written += 1
        next_write += period

    wall_end = time.perf_counter()
    handle.stop()
    cpu_seconds = time.process_time() - cpu_start
    wall_seconds = wall_end - wall_start
    overruns = reader.overruns

    reader.close()
    writer.close()
    writer.unlink()

    return {
        "target_hz": rate,
        "written": written,
        "delivered": delivered,
        "overruns": overruns,
        "write_hz": written / wall_seconds,
        "read_hz": delivered / wall_seconds,
        "cpu_pct": 100.0 * cpu_seconds / wall_seconds,
        "cpu_us_sample": 1e6 * cpu_seconds / max(written, 1),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rates", nargs="+", type=float,
        default=[10, 30, 60, 120, 200, 500, 1000],
    )
    parser.add_argument("--duration", type=float, default=2.0)
    parser.add_argument("--capacity", type=int, default=256)
    parser.add_argument("--elements", type=int, default=64)
    args = parser.parse_args()

    print(
        "target_hz written delivered overruns write_hz read_hz "
        "cpu_pct cpu_us_sample"
    )
    for rate in args.rates:
        result = run_rate(rate, args.duration, args.capacity, args.elements)
        print(
            f"{result['target_hz']:9.1f} {result['written']:7d} "
            f"{result['delivered']:9d} {result['overruns']:8d} "
            f"{result['write_hz']:8.1f} {result['read_hz']:7.1f} "
            f"{result['cpu_pct']:7.2f} {result['cpu_us_sample']:13.2f}"
        )


if __name__ == "__main__":
    main()
