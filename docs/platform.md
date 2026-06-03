# Platform Support

| OS | Segment | Notification |
|---|---|---|
| Linux | POSIX shared memory | adaptive poll on commit counter |
| macOS | POSIX shared memory | adaptive poll on commit counter |
| Windows | memory-mapped file | adaptive poll on commit counter |

Wheels: CPython 3.9–3.13 on manylinux x86_64/aarch64, macOS x86_64/arm64,
Windows amd64.

## Scale & CPU (measured)

Designed for many writers and many readers in one host alongside other work.
Measured on a 10-core Apple-silicon laptop (CPU % is of one core):

| stream | writer | reader (next) | reader (latest) |
|---|---|---|---|
| 100 KB/s | 0.3% | 0.7% | 0.7% |
| 2 MB/s | 1.4% | 1.8% | 1.7% |
| 100 MB/s | 2.3% | 3.0% | 2.9% |

Key properties for fan-out:

- **Writer CPU is flat in reader count** — 1.5% with 1 reader, 1.9% with 16
  readers @ 2 MB/s. The writer only bumps a counter; it never signals readers.
- **Readers are independent** — per-reader cost stays ~2% under fan-out.
- **Idle floor** of a quiescent reader is ~0.5% of a core at the default 2 ms
  poll cap. Raise `poll_max` to cut it: ~0.2% at a 10–50 ms cap (the residual is
  Python thread overhead, not polling). So ~300 mostly-idle readers cost roughly
  0.6–1.5 cores depending on `poll_max`. A future kernel-blocking backend will
  drop the idle floor further.

```python
gb.attach("name", poll_max=0.02)   # 20 ms cap: lower idle CPU, +<=20 ms latency
```

## Notification: why polling (for now)

The current release wakes readers by adaptively polling the shared commit
counter — fully portable, reliable everywhere, and near-0 CPU when idle (the
poll interval backs off to ~2 ms; measured ~0.5% of one core idle, sub-ms wake
latency). Both bounds are tunable via `global_buffer.notifier.Poller`.

A true 0-CPU kernel-blocking backend (Linux `eventfd` or a process-shared
pthread condvar, Windows named semaphore) fits behind the same interface and is
planned once it can be verified per-OS in CI. POSIX **named semaphores** were
evaluated and rejected: they behave unreliably on macOS (a second process gets
`EACCES` opening a peer's semaphore).

## Resource tracking

GlobalBuffer manages segment lifetime explicitly. It opts out of the
multiprocessing `resource_tracker` (via `track=False` on Python 3.13+, or by
unregistering on older versions) so a reader exiting can never unlink the owner's
segment. Clean up explicitly with `close()` + `unlink()`, or `gb.unlink(name)`
after a crash.

## Jetson / aarch64

Wheels are built for `manylinux aarch64`. Atomics and process-spawn behaviour can
differ from x86; run the test suite on the device once as a smoke test.
