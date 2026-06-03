# Platform Support

| OS | Segment | Notification |
|---|---|---|
| Linux | POSIX shared memory | adaptive poll on commit counter |
| macOS | POSIX shared memory | adaptive poll on commit counter |
| Windows | memory-mapped file | adaptive poll on commit counter |

Wheels: CPython 3.9–3.13 on manylinux x86_64/aarch64, macOS x86_64/arm64,
Windows amd64.

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
