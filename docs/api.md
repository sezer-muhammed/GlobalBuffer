# API Reference

## Module functions

### `gb.create(name, schema, capacity, max_bytes=None, heartbeat_interval=0.1) -> GlobalBuffer`
Create and own a named buffer (the writer). `schema` is a `gb.ArraySpec` or a
`pydantic.BaseModel` subclass, or generated protobuf `Message` class.
`max_bytes` sets the slot size for message buffers
(default 4096). `capacity` must be ≥ 1.
`heartbeat_interval` controls automatic writer liveness stamps in seconds;
zero stamps every write.

### `gb.attach(name, model=None, poll_min=None, poll_max=None) -> Reader`
Attach to an existing buffer (a reader). For message buffers, pass `model=` to
get validated instances and a schema-compatibility check on attach; omit it to
receive raw dicts for msgpack streams, or serialized bytes for protobuf streams.
`poll_max` raises the wakeup poll-backoff cap in seconds
(default ~2 ms) to lower idle CPU when running many readers, at the cost of up to
that much extra wake latency; `poll_min` sets the busy floor.

### `gb.unlink(name)`
Remove a named segment by name (e.g. clean up after a crash). No-op if absent.

## `gb.ArraySpec(dtype, shape)`
Declares an array stream. Properties: `np_dtype`, `itemsize`, `nbytes`.

## `gb.GlobalBuffer` (writer)
- `write(data)` — publish one sample (numpy array, or model/dict for messages).
- `reserve()` — context manager yielding a zero-copy ndarray view (array buffers).
- `heartbeat()` — stamp liveness (also done automatically on every write).
- `close()` / `unlink()` — detach / remove the segment.
- Usable as a context manager (`with gb.create(...) as w:`).

## `gb.Reader`
- `latest()` — newest sample or `None`.
- `next(timeout=None)` — next in-order sample; raises `gb.Empty` on timeout.
- `next_into(out, timeout=None)` — allocation-free array read into a reusable
  numpy destination; returns the sequence number.
- `next_batch_into(out, timeout=None)` — drains up to `out.shape[0]` array
  samples into a reusable numpy array shaped `(batch,)+reader.shape`; returns
  the number copied.
- `on_data(fn, mode="latest"|"next")` — background callback; returns a handle
  with `.stop()`.
- `overruns` — cumulative skipped samples (next mode).
- `writer_alive` — heartbeat-based liveness.
- `shape` / `dtype` / `nbytes` — array introspection (`None` for messages).
- `close()`; usable as a context manager.

## `gb.Consumer(Reader)`
Subclass and implement `callback(self)`; the framework sets `self.data` and
`self.seq` before each call.
- `Consumer.attach(name, model=None, mode="latest")` — construct.
- `start()` / `stop()` — run/stop the background dispatch thread.
- `dropped` — alias of `overruns`.

## Exceptions
All subclass `gb.GlobalBufferError`: `Empty`, `SchemaMismatch`, `BufferClosed`,
`BufferExists`, `BufferNotFound`.
