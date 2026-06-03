"""GlobalBuffer benchmark / showcase reader.

Start examples/writer.py first, then run as many of these as you like — each one
attaches to the same shared-memory buffer and reports its own throughput.

    python examples/reader.py                 # consume every sample in order
    python examples/reader.py --mode latest   # only ever read the newest frame
    python examples/reader.py --verify        # also check payload integrity
"""
import argparse
import time

import numpy as np

import global_buffer as gb


def main():
    ap = argparse.ArgumentParser(description="GlobalBuffer benchmark reader")
    ap.add_argument("--name", default="bench")
    ap.add_argument("--mode", choices=["next", "latest"], default="next",
                    help="next = every sample in order; latest = newest only")
    ap.add_argument("--verify", action="store_true",
                    help="check that every element equals the sequence stamp")
    ap.add_argument("--duration", type=float, default=0.0,
                    help="seconds to run (0 = until writer dies / Ctrl-C)")
    args = ap.parse_args()

    # wait for the writer to create the buffer
    r = None
    while r is None:
        try:
            r = gb.attach(args.name)
        except gb.BufferNotFound:
            time.sleep(0.05)

    nbytes = r.nbytes
    print(f"reader '{args.name}' [{args.mode}] attached: {tuple(r.shape)} {r.dtype}, "
          f"{nbytes / 1024:.1f} KiB/sample")

    n = bad = 0
    t0 = time.monotonic()
    last, last_n = t0, 0
    try:
        while True:
            if args.mode == "next":
                try:
                    arr = r.next(timeout=1.0)
                except gb.Empty:
                    if not r.writer_alive:
                        break
                    continue
            else:
                arr = r.latest()
                if arr is None:
                    if not r.writer_alive:
                        break
                    time.sleep(0.0005)
                    continue
            n += 1
            if args.verify and not np.all(arr == arr[0]):
                bad += 1

            now = time.monotonic()
            if now - last >= 1.0:
                rate = (n - last_n) / (now - last)
                vmsg = f"  bad={bad}" if args.verify else ""
                print(f"  recv {n:,} samples  {rate:,.0f}/s  "
                      f"{rate * nbytes / 1e6:,.1f} MB/s  "
                      f"total={n * nbytes / 1e6:,.1f} MB  overruns={r.overruns:,}{vmsg}")
                last, last_n = now, n
            if args.duration and now - t0 >= args.duration:
                break
    except KeyboardInterrupt:
        pass
    finally:
        dt = max(time.monotonic() - t0, 1e-9)
        total = n * nbytes
        vmsg = f", bad={bad}" if args.verify else ""
        print(f"reader done: {n:,} samples, {total / 1e6:,.1f} MB in {dt:.1f}s = "
              f"{n / dt:,.0f}/s, {total / 1e6 / dt:,.1f} MB/s, "
              f"overruns={r.overruns:,}{vmsg}")
        r.close()


if __name__ == "__main__":
    main()
