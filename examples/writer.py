"""GlobalBuffer benchmark / showcase writer.

Run ONE writer, then start several readers (examples/reader.py) in other
terminals — each reader reports how much data it's pulling through shared memory.

    python examples/writer.py --hz 1000 --size 4096
    python examples/writer.py --size 65536            # unthrottled, big frames

Each sample is stamped with its sequence number in element 0 and the whole frame
is filled with that value, so readers can verify integrity (--verify).
"""
import argparse
import time

import numpy as np

import global_buffer as gb


def main():
    ap = argparse.ArgumentParser(description="GlobalBuffer benchmark writer")
    ap.add_argument("--name", default="bench")
    ap.add_argument("--hz", type=float, default=0.0,
                    help="target samples/sec (0 = as fast as possible)")
    ap.add_argument("--size", type=int, default=4096,
                    help="elements per sample (the 'data length')")
    ap.add_argument("--dtype", default="float32")
    ap.add_argument("--capacity", type=int, default=16)
    ap.add_argument("--duration", type=float, default=0.0,
                    help="seconds to run (0 = until Ctrl-C)")
    args = ap.parse_args()

    spec = gb.ArraySpec(args.dtype, (args.size,))
    buf = gb.create(name=args.name, schema=spec, capacity=args.capacity)
    nbytes = spec.nbytes
    period = 1.0 / args.hz if args.hz > 0 else 0.0
    print(f"writer '{args.name}': {args.size} x {args.dtype} = "
          f"{nbytes / 1024:.1f} KiB/sample, "
          f"hz={'max' if args.hz == 0 else args.hz}, capacity={args.capacity}")

    i = 0
    t0 = time.monotonic()
    last, last_i = t0, 0
    next_t = t0
    try:
        while True:
            with buf.reserve() as slot:        # zero-copy fill in place
                slot[:] = i                    # whole frame = seq (real data move)
            i += 1
            now = time.monotonic()
            if now - last >= 1.0:
                rate = (i - last_i) / (now - last)
                print(f"  wrote {i:,} samples  {rate:,.0f}/s  "
                      f"{rate * nbytes / 1e6:,.1f} MB/s")
                last, last_i = now, i
            if args.duration and now - t0 >= args.duration:
                break
            if period:
                next_t += period
                sleep = next_t - time.monotonic()
                if sleep > 0:
                    time.sleep(sleep)
    except KeyboardInterrupt:
        pass
    finally:
        dt = max(time.monotonic() - t0, 1e-9)
        print(f"writer done: {i:,} samples in {dt:.1f}s = {i / dt:,.0f}/s, "
              f"{i * nbytes / 1e6 / dt:,.1f} MB/s avg")
        buf.close()
        buf.unlink()


if __name__ == "__main__":
    main()
