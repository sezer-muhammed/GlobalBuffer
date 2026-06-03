"""Entrypoints run in child processes by test_crossproc.py."""
import sys
import time

import numpy as np

import global_buffer as gb


def array_reader_count(name, expected_max, out_path):
    expected_max = int(expected_max)
    r = gb.attach(name)
    seen = set()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        v = r.latest()
        if v is not None:
            seen.add(int(v[0]))
        if len(seen) >= expected_max:
            break
        time.sleep(0.001)
    with open(out_path, "w") as f:
        f.write(str(len(seen)))
    r.close()


def array_reader_torn(name, n_samples, out_path):
    """Read in next mode; verify every payload is internally consistent (all
    elements equal the seq-derived value) -> proves no torn reads."""
    n_samples = int(n_samples)
    r = gb.attach(name)
    bad = 0
    count = 0
    deadline = time.monotonic() + 20
    while count < n_samples and time.monotonic() < deadline:
        try:
            arr = r.next(timeout=1.0)
        except gb.Empty:
            break
        v = int(arr[0])
        if not np.all(arr == v):
            bad += 1
        count += 1
    with open(out_path, "w") as f:
        f.write(f"{count},{bad},{r.overruns}")
    r.close()


if __name__ == "__main__":
    fn = sys.argv[1]
    globals()[fn](*sys.argv[2:])
