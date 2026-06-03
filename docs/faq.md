# FAQ

### Why does `reader.py --mode latest --spin` report enormous MB/s?

`--spin` busy-loops `latest()` and counts every read, so it rereads the *same*
current frame millions of times — that number is shared-memory **reread
bandwidth**, not inter-process throughput, and it pins a CPU core. The default
reader uses the efficient blocking-callback path and reports the writer's real
rate. Use `--spin` only as a bandwidth curiosity.

### Is it zero-copy?

The **write** side is: `reserve()` yields an ndarray view directly into the slot.
The **read** side currently copies the payload out of shared memory. Read-side
zero-copy primitives exist in the core (`read_view_info` / `validate`) and are a
planned reader feature.

### Does it really use 0 CPU when idle?

Near-0. Readers adaptively poll the shared commit counter (a single atomic load),
backing off to a cap when idle (~0.2–0.5% of a core). Raise `poll_max` to lower
it further for many readers. A true kernel-blocking backend is planned.

### Can I have multiple writers on one buffer?

No — one writer (owner) per buffer. `create()` raises `BufferExists` if the name
is taken. Run separate buffers for separate producers.

### A reader attached after the writer sent data and got nothing from `next()`.

A reader starts at the newest sample present **at attach time**, so `next()` only
returns samples written *after* attach. Use `latest()` to read the current value,
or start the reader before the writes you care about.

### A process crashed and now `create()` says the buffer exists.

The segment leaked. Remove it with `gb.unlink("name")`, then recreate.

### How many readers can one writer feed?

The writer never signals readers (it just bumps a counter), so its CPU is flat in
reader count. See [platform.md](platform.md) for measured fan-out numbers and
`poll_max` tuning for large reader counts.
