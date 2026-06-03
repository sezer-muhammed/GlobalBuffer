"""Read validated Status messages in order."""
import pydantic

import global_buffer as gb


class Status(pydantic.BaseModel):
    gain: float
    cam_on: bool
    pod: str


def main():
    r = gb.attach("status", model=Status)
    print("reading 'status'; Ctrl-C to stop")
    try:
        while True:
            print(r.next(timeout=5.0))
    except (KeyboardInterrupt, gb.Empty):
        pass
    finally:
        r.close()


if __name__ == "__main__":
    main()
