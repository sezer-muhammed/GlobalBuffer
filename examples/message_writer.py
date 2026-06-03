"""Publish a 1 Hz pydantic status message."""
import time

import pydantic

import global_buffer as gb


class Status(pydantic.BaseModel):
    gain: float
    cam_on: bool
    pod: str


def main():
    buf = gb.create(name="status", schema=Status, capacity=4, max_bytes=512)
    print("writing 'status' at 1 Hz; Ctrl-C to stop")
    try:
        i = 0
        while True:
            buf.write(Status(gain=1.0 + 0.1 * i, cam_on=bool(i % 2), pod="dev6"))
            i += 1
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        buf.close()
        buf.unlink()


if __name__ == "__main__":
    main()
