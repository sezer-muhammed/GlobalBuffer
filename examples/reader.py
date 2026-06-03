"""GlobalBuffer benchmark / showcase reader.

Start examples/writer.py first, then run as many of these as you like — each one
attaches to the same shared-memory buffer and reports its own throughput.

    python examples/reader.py                 # consume every sample in order
    python examples/reader.py --mode latest   # only ever process the newest frame
    python examples/reader.py --verify        # also check payload integrity
    python examples/reader.py --mode latest --spin   # raw reread-bandwidth demo

By default this uses the EFFICIENT path: a background callback that blocks until a
new sample arrives (near-0 CPU when idle) and processes each sample once. The
reported rate therefore tracks the writer's real rate.

`--spin` (latest only) instead busy-loops calling latest() as fast as possible and
counts every read. That measures raw shared-memory reread bandwidth of the current
frame — a fun, large number, but it re-reads the SAME frame repeatedly and pins a
CPU core. It is NOT inter-process throughput; use it only as a bandwidth demo.
"""
import argparse
import threading
import time

import numpy as np

import global_buffer as gb


def run_efficient(r, mode, verify, duration):
    """Process each new sample once via a blocking background callback."""
    nbytes = r.nbytes
    state = {"n": 0, "skipped": 0, "bad": 0, "last_seq": -1}
    lock = threading.Lock()

    def cb(sample, seq):
        with lock:
            state["n"] += 1
            if state["last_seq"] >= 0:
                # in latest mode, frames the writer made that we coalesced past
                state["skipped"] += max(0, seq - state["last_seq"] - 1)
            state["last_seq"] = seq
            if verify and not np.all(sample == sample.flat[0]):
                state["bad"] += 1

    handle = r.on_data(cb, mode=mode)
    t0 = time.monotonic()
    last, last_n = t0, 0
    try:
        while True:
            time.sleep(1.0)
            with lock:
                n, skipped, bad = state["n"], state["skipped"], state["bad"]
            now = time.monotonic()
            rate = (n - last_n) / (now - last)
            vmsg = f"  bad={bad}" if verify else ""
            smsg = f"  skipped={skipped:,}" if mode == "latest" else \
                   f"  overruns={r.overruns:,}"
            print(f"  recv {n:,} samples  {rate:,.0f}/s  "
                  f"{rate * nbytes / 1e6:,.1f} MB/s  "
                  f"total={n * nbytes / 1e6:,.1f} MB{smsg}{vmsg}")
            last, last_n = now, n
            if duration and now - t0 >= duration:
                break
            if not r.writer_alive and n == last_n:
                break
    except KeyboardInterrupt:
        pass
    finally:
        handle.stop()
        dt = max(time.monotonic() - t0, 1e-9)
        with lock:
            n, skipped, bad = state["n"], state["skipped"], state["bad"]
        total = n * nbytes
        vmsg = f", bad={bad}" if verify else ""
        smsg = f", skipped={skipped:,}" if mode == "latest" else \
               f", overruns={r.overruns:,}"
        print(f"reader done: {n:,} samples, {total / 1e6:,.1f} MB in {dt:.1f}s = "
              f"{n / dt:,.0f}/s, {total / 1e6 / dt:,.1f} MB/s{smsg}{vmsg}")


def run_spin(r, verify, duration):
    """Busy-loop latest() to measure raw reread bandwidth (NOT real throughput)."""
    nbytes = r.nbytes
    print("  [--spin] busy-looping latest(): rereads the SAME current frame as "
          "fast as possible; pins a CPU core. Not inter-process throughput.")
    n = bad = 0
    t0 = time.monotonic()
    last, last_n = t0, 0
    try:
        while True:
            arr = r.latest()
            if arr is None:
                if not r.writer_alive:
                    break
                continue
            n += 1
            if verify and not np.all(arr == arr.flat[0]):
                bad += 1
            now = time.monotonic()
            if now - last >= 1.0:
                rate = (n - last_n) / (now - last)
                vmsg = f"  bad={bad}" if verify else ""
                print(f"  reread {n:,}x  {rate:,.0f}/s  "
                      f"{rate * nbytes / 1e6:,.1f} MB/s reread-bw{vmsg}")
                last, last_n = now, n
            if duration and now - t0 >= duration:
                break
    except KeyboardInterrupt:
        pass
    finally:
        dt = max(time.monotonic() - t0, 1e-9)
        print(f"reader done (spin): {n:,} rereads in {dt:.1f}s = {n / dt:,.0f}/s, "
              f"{n * nbytes / 1e6 / dt:,.1f} MB/s reread-bw"
              + (f", bad={bad}" if verify else ""))


def main():
    ap = argparse.ArgumentParser(description="GlobalBuffer benchmark reader")
    ap.add_argument("--name", default="bench")
    ap.add_argument("--mode", choices=["next", "latest"], default="next",
                    help="next = every sample in order; latest = newest only")
    ap.add_argument("--verify", action="store_true",
                    help="check that every element equals the sequence stamp")
    ap.add_argument("--spin", action="store_true",
                    help="(latest only) busy-loop reread-bandwidth demo")
    ap.add_argument("--duration", type=float, default=0.0,
                    help="seconds to run (0 = until writer dies / Ctrl-C)")
    args = ap.parse_args()

    r = None
    while r is None:
        try:
            r = gb.attach(args.name)
        except gb.BufferNotFound:
            time.sleep(0.05)

    label = "latest" if args.mode == "latest" else "next"
    print(f"reader '{args.name}' [{label}] attached: {tuple(r.shape)} {r.dtype}, "
          f"{r.nbytes / 1024:.1f} KiB/sample")

    try:
        if args.spin and args.mode == "latest":
            run_spin(r, args.verify, args.duration)
        else:
            run_efficient(r, args.mode, args.verify, args.duration)
    finally:
        r.close()


if __name__ == "__main__":
    main()
