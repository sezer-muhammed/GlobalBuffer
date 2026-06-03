# API Reference

## Module functions

### `gb.create(name, schema, capacity, max_bytes=None) -> GlobalBuffer`
Create and own a named buffer (the writer). `schema` is a `gb.ArraySpec` or a
`pydantic.BaseModel` subclass. `max_bytes` sets the slot size for message buffers
(default 4096). `capacity` must be ≥ 1.

### `gb.attach(name, model=None) -> Reader`
Attach to an existing buffer (a reader). For message buffers, pass `model=` to
get validated instances and a schema-compatibility check on attach; omit it to
receive raw dicts.

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
