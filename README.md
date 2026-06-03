# GlobalBuffer

Cross-platform, cross-process **named shared-memory buffer** for Python.

`import global_buffer as gb`

A writer publishes samples by name; any process on the same host attaches by name
and reads — either the newest sample or every sample in order, by blocking call or
background callback. Built for streams that mix **high frequency** (e.g. 200 Hz
numeric arrays) and **low frequency** (e.g. 1 Hz structured status messages)
without burning CPU on either end.

It fills the gap between `multiprocessing.shared_memory` (too low-level),
`UltraDict` (dated, pickle-based), and iceoryx2/eCAL (heavy native installs):
a pip-installable, pydantic-native, callback-driven buffer with a clean API and a
lock-free Cython hot path.

## Status

**v1.0.0.** Core is stable and covered by 70 tests (including a cross-process
no-torn-reads stress test), verified on macOS / CPython 3.14. Linux, Windows and
aarch64 (Jetson) are supported and wheels are configured, with broad CI
verification on those platforms in progress. See [`CHANGELOG.md`](CHANGELOG.md)
for known limitations.

## Features

- **Two stream kinds, one API**
  - **Array streams** — fixed dtype + shape numpy data, written and read **zero-copy**.
  - **Message streams** — `pydantic` models on the public API, `msgspec` (msgpack) on the wire (~10× faster than pickle).
- **Last-value or in-order reads** — `latest()` jumps to the newest sample;
  `next()` consumes every sample in order and reports `overruns` if a reader falls behind.
- **Lock-free, tear-free** — single-writer / multi-reader ring with a spare slot
  (`capacity + 1`) plus a per-slot seqlock implemented with C11 atomics. No torn reads even at high rate.
- **Near-0-CPU wakeups** — readers block on an adaptive poll of the shared commit
  counter; idle readers cost roughly one atomic load every couple of milliseconds.
- **Cross-platform** — Linux, macOS, Windows; ships as compiled wheels.

## Install

```bash
pip install global_buffer
```

Wheels are published for CPython 3.9–3.13 on manylinux x86_64 / aarch64,
macOS (x86_64 + arm64) and Windows amd64. A source build needs a C11 compiler.

## Quickstart

### Array stream (200 Hz, zero-copy)

```python
import global_buffer as gb
import numpy as np

# writer / owner
csi = gb.create(name="csi", schema=gb.ArraySpec(dtype="complex64", shape=(64, 4)),
                capacity=8)

with csi.reserve() as slot:      # slot is an ndarray view directly into shm
    slot[:] = frame              # fill in place — no copy
# or: csi.write(frame)           # single-memcpy convenience form

# reader (any other process)
r = gb.attach("csi")             # schema discovered from the segment
frame = r.latest()               # newest committed sample
r.on_data(lambda sample, seq: process(sample), mode="latest")  # bg thread
```

### Message stream (1 Hz, pydantic)

```python
import pydantic, global_buffer as gb

class Status(pydantic.BaseModel):
    gain: float
    cam_on: bool

status = gb.create(name="status", schema=Status, capacity=4, max_bytes=512)
status.write(Status(gain=1.2, cam_on=True))

rs = gb.attach("status", model=Status)   # schema mismatch -> raises on attach
msg = rs.next(timeout=1.0)               # -> validated Status instance
```

### OO consumer

```python
class CsiConsumer(gb.Consumer):
    def callback(self):                  # framework sets self.data / self.seq
        self.processed = heavy_process(self.data)

ob = CsiConsumer.attach("csi", mode="latest")
ob.start()
...
ob.stop()
```

## Semantics

- `capacity` is the number of logical slots; the core allocates `capacity + 1` so
  the writer never overwrites the slot a reader could currently be reading.
- A reader created with `attach()` starts at the newest sample present at attach time.
- `latest()` returns `None` on an empty buffer. `next(timeout=...)` raises
  `gb.Empty` on timeout; without a timeout it blocks.
- `next()` accumulates `reader.overruns` when the writer laps the reader by more
  than `capacity` samples (the reader then jumps to the oldest still-available sample).
- `reader.writer_alive` reflects a heartbeat the writer stamps on every write
  (a writer silent for >2 s reads as not alive).

## Lifecycle

```python
buf.close()    # detach this handle (segment stays alive)
buf.unlink()   # owner removes the segment
gb.unlink(name)  # remove a segment by name (e.g. clean up after a crash)
```

GlobalBuffer manages segment lifetime explicitly (it opts out of the
multiprocessing `resource_tracker` where supported, Python 3.13+), so a reader
exiting never unlinks the owner's segment.

## Platform support

| OS | Segment | Notification |
|---|---|---|
| Linux | `multiprocessing.shared_memory` (POSIX shm) | adaptive poll on commit counter |
| macOS | `multiprocessing.shared_memory` (POSIX shm) | adaptive poll on commit counter |
| Windows | `multiprocessing.shared_memory` (mem-mapped) | adaptive poll on commit counter |

> **Verification status.** Behaviour is verified on macOS today; the Linux/Windows
> CI matrix and aarch64 wheels are configured and will be exercised before those
> platforms are declared production-verified.
>
> **Note on notifications.** The current release uses adaptive polling of the
> shared commit counter for wakeups — fully portable, reliable on all three OSes,
> and near-0 CPU when idle (the poll interval backs off to ~2 ms). A true 0-CPU
> kernel-blocking backend (Linux `eventfd` / process-shared pthread condvar,
> Windows named semaphore) fits behind the same interface and is planned once it
> can be verified per-OS in CI. POSIX named semaphores were evaluated and dropped:
> they behave unreliably on macOS.

## Build from source

```bash
python -m pip install -U pip setuptools wheel Cython numpy msgspec pydantic
python setup.py build_ext --inplace
PYTHONPATH=src python -c "import global_buffer as gb; print(gb.__version__)"
```

## Run the tests

```bash
PYTHONPATH=src python -m pytest tests -v                 # full suite
PYTHONPATH=src python -m pytest tests -m "not crossproc_slow"   # skip the long stress test
```

Or in Docker:

```bash
docker build -t globalbuffer . && docker run --rm globalbuffer
docker compose up   # two-process writer/reader demo
```

## Jetson / aarch64

Wheels are built for `manylinux aarch64`. Atomics and process spawn behaviour can
differ from x86; run the suite on the target device once as a smoke test.

## Design

Full documentation is in [`docs/`](docs/index.md); design rationale and the
on-disk segment layout are in [`docs/design.md`](docs/design.md).

## License

MIT © 2026 Izzet Sezer
