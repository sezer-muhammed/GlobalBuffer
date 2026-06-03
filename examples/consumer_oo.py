"""OO consumer: subclass Consumer, implement callback(self). Self-contained demo."""
import time

import numpy as np

import global_buffer as gb


class CsiConsumer(gb.Consumer):
    def callback(self):
        self.processed = float(np.abs(self.data).mean())
        print(f"seq={self.seq} processed={self.processed:.3f}")


def main():
    w = gb.create(name="csi_demo", schema=gb.ArraySpec("complex64", (64, 4)),
                  capacity=8)
    ob = CsiConsumer.attach("csi_demo", mode="latest")
    ob.start()
    try:
        for i in range(20):
            with w.reserve() as slot:
                slot[:] = np.full((64, 4), i, dtype=np.complex64)
            time.sleep(0.05)
        time.sleep(0.2)
    finally:
        ob.stop()
        w.close()
        w.unlink()


if __name__ == "__main__":
    main()
