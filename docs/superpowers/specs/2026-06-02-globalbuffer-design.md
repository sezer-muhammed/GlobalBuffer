# GlobalBuffer — Design Spec

**Date:** 2026-06-02
**Status:** Approved design, pre-implementation
**Package:** `GlobalBuffer` · `import global_buffer as gb`

## 1. Purpose

A cross-platform, cross-process **named shared-memory buffer** with last-value /
ring semantics. A writer publishes samples by name; any process on the same host
attaches by name and reads — either the newest sample or every sample in order,
via blocking call or callback. Built for streams that mix **high frequency**
(e.g. 200 Hz numeric arrays) and **low frequency** (e.g. 1 Hz structured status
messages) without burning CPU on either end.

It fills the gap between `multiprocessing.shared_memory` (too low-level),
`UltraDict` (dated, pickle-based), and iceoryx2/eCAL (heavy native installs):
a pip-installable, pydantic-native, callback-driven buffer with a clean API.

## 2. Scope

- **One named buffer = one stream of one declared type.** Two kinds:
  - **Array stream** — fixed dtype + shape numeric data (numpy), zero-copy.
  - **Message stream** — structured records (pydantic public API, msgspec wire codec).
- A typical deployment runs several independent buffers (e.g. a 200 Hz CSI array
  buffer + a 1 Hz status message buffer). "One API" means the same classes handle
  both kinds via the declared schema — **not** mixing types in a single buffer.
- Same-host, multi-process. **Not** networked / multi-host (that's eCAL/DDS territory).

### Out of scope (YAGNI)

- GPU / VRAM buffers (separate future concern; this is host RAM).
- Cross-host / network transport.
- Persistence to disk beyond the lifetime of the segment.
- Mixed-type payloads within a single buffer.

## 3. Public API

```python
import global_buffer as gb
import numpy as np

# --- Array stream (writer / owner) ---
csi = gb.create(
    name="csi",
    schema=gb.ArraySpec(dtype="complex64", shape=(64, 4)),
    capacity=8,                 # logical slots; core allocates capacity + 1 (spare)
)

# zero-copy write: fill the slot view in place
with csi.reserve() as slot:     # slot is an ndarray view directly into shm
    slot[:] = frame
# or copy write
csi.write(frame)

# --- Message stream (writer / owner) ---
import pydantic
class Status(pydantic.BaseModel):
    gain: float
    cam_on: bool

status = gb.create(name="status", schema=Status, capacity=4, max_bytes=512)
status.write(Status(gain=1.2, cam_on=True))

# --- Reader (any separate process) ---
r = gb.attach("csi")            # schema discovered from segment header
frame = r.latest()              # newest committed sample (coalesced)
frame = r.next(timeout=1.0)     # consume in order; raises Empty/returns None on timeout
print(r.overruns)               # samples skipped because reader fell behind (next mode)
print(r.writer_alive)           # heartbeat-based liveness

# --- Functional callback — background thread, 0-CPU blocking wake ---
handle = r.on_data(lambda sample, seq: ..., mode="latest")  # or mode="next"
handle.stop()

# --- OO consumer: subclass, write only callback(self) ---
class CsiConsumer(gb.Consumer):
    def callback(self):              # no args, no return
        # framework has set self.data (zero-copy view) and self.seq before the call
        self.processed = heavy_process(self.data)   # store result on self

ob = CsiConsumer.attach("csi", mode="latest")  # zero_copy=True default for arrays
ob.start()                            # background thread; non-blocking to main
...
ob.processed                          # main thread reads the result later
print(ob.dropped)                     # samples skipped (callback slower than arrival / staleness)
ob.stop()

# typed message reader (validation on read)
rs = gb.attach("status", model=Status)   # schema_hash mismatch -> raises on attach
msg = rs.latest()                          # -> validated Status instance

# lifecycle
csi.close()      # detach this handle
csi.unlink()     # owner removes the segment (explicit)
```

**Naming:** `gb.create(...)` returns a writer/owner handle; `gb.attach(...)` returns
a reader handle. Underlying classes `gb.GlobalBuffer` (writer), `gb.Reader`, and
`gb.Consumer` (subclassable reader). `gb.Consumer` *is* a `gb.Reader` that owns its
own dispatch thread and calls `self.callback()` instead of taking a function.

## 4. Architecture

### 4.1 Layers

- **`_core` (Cython/C):** segment layout, atomic `latest_seq`
  (release-store on commit / acquire-load on read), seqlock read validation,
  slot memcpy, notifier signaling. No Python on the hot path; real C11 atomics.
- **Python layer:** `GlobalBuffer` / `Reader`, schema handling, pydantic↔msgspec
  bridge, callback-dispatch thread, lifecycle & registry management.

### 4.2 Memory layout (single shm segment via `multiprocessing.shared_memory`)

```
[ Header ]
    magic, version, kind (ARRAY | MSG),
    n_slots (= capacity + 1), slot_size,
    latest_seq (atomic u64), writer_heartbeat (u64 monotonic ticks),
    ARRAY: dtype_code, ndim, shape[NDIM_MAX]
    MSG:   max_bytes, schema_hash, schema_json_len, schema_json[...]
[ Reader registry ]
    max_readers × { pid, notifier_id, last_seen_seq, alive_flag, heartbeat }
[ Slots ]
    n_slots × { seq (u64), length (u32), payload[slot_size] }
```

### 4.3 Ring & tear-free reads (the N+1 spare-slot scheme)

- Single writer, multiple readers. `write_index = latest_seq % n_slots`.
- Allocating `capacity + 1` slots guarantees the writer never overwrites the slot
  a reader could currently be reading.
- **Seqlock read:** reader records `slot.seq`, reads payload, re-reads `slot.seq`;
  if it changed, the slot was recycled mid-read → retry (`latest`) or count an
  overrun and advance (`next`). Lock-free hot path, no torn reads.

### 4.4 Two write paths

- **Array (zero-copy):** `reserve()` yields an ndarray view over the target slot;
  caller fills in place, context-exit bumps `latest_seq` (release) and signals
  readers. `write(arr)` is the single-memcpy convenience form. Never serialized.
- **Message (pydantic → msgspec):** validate/encode with msgspec (msgpack) into the
  slot, set `length`, bump `latest_seq`, signal. pydantic is the public type;
  msgspec is the wire codec (~10× faster than pydantic-native dumping).

### 4.5 Read paths (per-reader configurable)

- `latest()` — jump to newest committed sample, coalescing.
- `next(timeout)` — consume in order from the reader's cursor; if lapped beyond
  `capacity`, skip to oldest-available and increment `overruns`.
- `on_data(cb, mode)` — background thread blocks on the notifier and dispatches.

### 4.6 Notification (cross-platform, 0-CPU blocking)

One `Notifier` interface, best backend chosen per OS at runtime:

| OS | Backend | Blocking |
|---|---|---|
| Linux | `eventfd` (or POSIX named semaphore) | yes, 0 CPU |
| macOS | POSIX named semaphore via `ctypes` (`sem_open`) | yes, 0 CPU |
| Windows | named semaphore via `ctypes` (`CreateSemaphoreW`) | yes, 0 CPU |
| fallback | adaptive polling (fast spin → back off when idle) | near-0 CPU idle |

All real backends are **named kernel objects**, so independent programs attach by
name. Counting semaphores wake one waiter per signal, so the writer signals
**each registered reader's own** notifier (readers register a notifier in the
registry on attach) — avoids needing a cross-platform broadcast primitive.
In `latest` mode the reader drains/coalesces the notifier and reads once.

## 5. Failure modes

| Condition | Handling |
|---|---|
| Torn read | N+1 spare slot + seqlock recheck. |
| Reader dies | Registry slot reclaimed via pid-liveness (`os.kill(pid, 0)`) + heartbeat so it can't fill up; signaling a dead notifier is harmless. |
| Writer dies | `writer_heartbeat` in header; `latest()` returns last good sample, `next(timeout)` times out, `reader.writer_alive` exposed. |
| `resource_tracker` premature unlink (POSIX) | Unregister the segment from `multiprocessing.resource_tracker` on attach so a reader's exit can't unlink it; only the owner calls `unlink()`. |
| Stale / incompatible segment | magic + version + `schema_hash` checked on attach; mismatch raises. |
| Crash leaks segment | `gb.unlink(name)` / `GlobalBuffer.unlink()`; optional auto-unlink when owner exits cleanly. |

## 6. Packaging & dependencies

- **`_core`** compiled with Cython; built into **prebuilt wheels** via
  `cibuildwheel` for cp39–cp313 × {manylinux x86_64, manylinux aarch64 (Jetson),
  macOS x86_64 + arm64, Windows amd64}. `pip install` needs no compiler
  (numpy/opencv model). Source sdist still compiles where no wheel exists.
- **Runtime deps:** `numpy` (buffer protocol / ndarray views), `pydantic`
  (message public API), `msgspec` (wire codec). `ctypes` is stdlib.
- Array-only use could keep pydantic optional via an extra; default install
  includes it for the documented API.

## 7. Testing

- **Unit:** ring wraparound, concurrent writer/reader seqlock stress, overrun
  counting, schema-hash mismatch, reserve()-in-place correctness.
- **Cross-process integration:** separate programs attach by name; measure
  notification latency; assert no torn reads at 200 Hz+; assert 0-CPU idle for a
  1 Hz reader.
- **CI matrix:** GitHub Actions ubuntu / macOS / windows.
- **aarch64 / Jetson smoke test:** spawn-only and atomics behavior differ from the
  x86 lab — verify on real hardware.

## 8. Open questions / deferred

- GPU buffer variant (CUDA IPC on discrete GPUs; unified memory on Jetson) — a
  natural follow-on, explicitly deferred.
- Optional `wait_all`/barrier helpers for multi-stream consumers — add only if a
  real use case appears.
