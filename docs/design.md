# Design

## Layers

- **`_core` (Cython + C11 atomics)** — segment layout math, the per-slot seqlock,
  the commit counter, slot memcpy. No Python on the hot path.
- **Python layer** — schema handling, the pydantic/msgspec and protobuf bridges, lifecycle and
  the adaptive-poll wakeup.

## Memory layout

One `multiprocessing.shared_memory` segment per buffer:

```
[ Header 4096B ]  magic, version, kind, n_slots, slot_stride, slot_size,
                  payload_off, latest_count (atomic u64), writer_pid,
                  writer_heartbeat (atomic u64), offsets, schema_hash,
                  ARRAY: dtype[16] + ndim + shape[8]
                  MSG:   schema_json
[ Reader registry ]  reserved (64 × 64B) for a future kernel-blocking fast path
[ Slots ]  n_slots × { lock (atomic u32), seq (atomic u64), length, payload }
```

`slots_off` is page-aligned; payload starts 64B into each slot (cache aligned).

## Tear-free single-writer / multi-reader

- The writer publishes sample `S` into slot `S % n_slots`, then releases the new
  `latest_count`.
- Allocating `capacity + 1` slots guarantees the writer never lands on the slot
  holding the newest readable sample.
- **Seqlock:** the writer bumps the slot `lock` to odd before writing and to even
  after; a reader reads `lock`, the payload, then re-reads `lock` and the `seq` —
  a mismatch means the slot was recycled mid-read, so it retries (`latest`) or
  counts an overrun and advances (`next`). All ordering uses C11
  acquire/release atomics.

## Notification

The writer bumping `latest_count` *is* the signal. Readers block by adaptively
polling that counter (50 µs → 2 ms backoff). This is portable and reliable on all
three OSes; a true 0-CPU kernel-blocking backend fits behind the same interface
(see [platform.md](platform.md)).

## What's deferred

GPU/VRAM buffers, networked/multi-host transport, and a `wait_all` multi-stream
barrier are intentionally out of scope for now.
