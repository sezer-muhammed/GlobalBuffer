# Concepts

## One buffer, one stream, one type

A named buffer carries a single stream of a single declared type — either an
**array stream** (fixed dtype + shape, zero-copy) or a **message stream**
(pydantic on the API, msgpack on the wire). Run several buffers for several
streams (e.g. a 200 Hz CSI array buffer plus a 1 Hz status message buffer).

## Slots and the spare

`capacity` is the number of logical slots. The core allocates `capacity + 1` so
the writer never overwrites the exact slot a reader is mid-read. Combined with a
per-slot seqlock, reads are tear-free without locking the writer.

## Read modes

- **`latest()`** — jump to the newest committed sample (coalescing). Returns
  `None` on an empty buffer. Ideal when you only care about the current value.
- **`next(timeout)`** — consume every sample in order from this reader's cursor.
  Raises `Empty` on timeout. If the writer laps the reader by more than
  `capacity`, the reader skips to the oldest still-available sample and adds the
  gap to `reader.overruns`.
- **`on_data(fn, mode=...)`** — a background thread that calls `fn(sample, seq)`
  as samples arrive, in either mode.

A reader created with `attach()` starts at the newest sample present **at attach
time** — so a reader should usually be up before the writes it cares about.

## Liveness

The writer stamps a monotonic heartbeat on every write. `reader.writer_alive`
is `False` if no heartbeat has landed for >2 s, so readers can detect a dead or
stalled writer.

## CPU behaviour

Readers wake via adaptive polling of the shared commit counter: idle readers
back off to ~2 ms between checks (a single atomic load each), so a quiescent
reader costs almost nothing; an active reader keeps up at the writer's rate. See
[platform.md](platform.md) for the rationale and future kernel-blocking path.
