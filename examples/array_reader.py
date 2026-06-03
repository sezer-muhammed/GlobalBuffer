"""Read the newest 'csi' frame as it arrives, near-0 CPU when idle."""
import time

import global_buffer as gb


def main():
    r = gb.attach("csi")
    print("reading 'csi'; Ctrl-C to stop")

    def on_frame(frame, seq):
        print(f"seq={seq} mean={frame.mean():.1f} shape={frame.shape}")

    h = r.on_data(on_frame, mode="latest")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        h.stop()
        r.close()


if __name__ == "__main__":
    main()
