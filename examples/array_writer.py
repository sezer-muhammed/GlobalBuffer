"""Publish a 200 Hz array stream. Run alongside array_reader.py."""
import time

import numpy as np

import global_buffer as gb


def main():
    buf = gb.create(name="csi", schema=gb.ArraySpec("complex64", (64, 4)), capacity=8)
    print("writing 'csi' at 200 Hz; Ctrl-C to stop")
    i = 0
    try:
        while True:
            with buf.reserve() as slot:          # zero-copy fill in place
                slot[:] = np.full((64, 4), i, dtype=np.complex64)
            i += 1
            time.sleep(1 / 200)
    except KeyboardInterrupt:
        pass
    finally:
        buf.close()
        buf.unlink()


if __name__ == "__main__":
    main()
