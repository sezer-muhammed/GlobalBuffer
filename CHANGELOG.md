# Changelog

All notable changes to GlobalBuffer are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/);
this project uses semantic versioning.

## 1.1.3 — 2026-08-22

### Fixed
- Keep the protobuf test fixture compatible with current protobuf releases,
  where `DescriptorPool.Add()` no longer returns the file descriptor.

## 1.1.2 — 2026-08-22

### Fixed
- Constrain the runtime NumPy dependency below 2.5 as well as the isolated
  build dependency, so manylinux2014 wheel installation does not trigger a
  NumPy source build requiring GCC 10.3.

## 1.1.1 — 2026-08-22

### Fixed
- Pin the isolated build-time NumPy dependency below 2.5 so manylinux2014
  wheels do not fall back to a NumPy source build requiring GCC 10.3.

## 1.1.0 — 2026-08-22

### Added
- Protobuf message classes as schemas, with native protobuf binary encoding,
  decoding, and descriptor-based schema compatibility checks.
- Allocation-free array reads through `Reader.next_into()` and batched reads
  through `Reader.next_batch_into()`.
- Multi-rate payload and CPU-efficiency benchmark tooling, including 32 KiB
  `int8` payload tests.

### Changed
- Persistent Cython shared-memory bindings remove repeated buffer-export setup
  from the writer and reader hot paths.
- Automatic writer heartbeats are throttled to 100 ms by default; pass
  `heartbeat_interval=0` to stamp every write.
- Added protobuf to runtime dependencies and expanded release documentation.

## 1.0.2 — 2026-06-03

### Fixed
- **cibuildwheel test collection failure**: `tests/conftest.py` was prepending
  the source `src/` tree to `sys.path`, shadowing the installed wheel inside
  cibuildwheel's clean test venv (which has no `_core.so` in the source tree).
  Removed the manual `sys.path.insert`; cibuildwheel installs the wheel before
  running tests, so `import global_buffer` resolves from site-packages. Local
  development continues to work via `pip install -e .` or `PYTHONPATH=src` with
  the extension built in-place.
- **cross-process subprocess `PYTHONPATH`**: `test_crossproc.py` was
  unconditionally passing `PYTHONPATH=<src>` to child processes, which also
  shadowed the installed wheel in cibuildwheel. It now only sets `PYTHONPATH`
  when `_core.so/.pyd` is detected in the source tree (i.e. built in-place).
- **Windows cmd.exe marker expression**: the cibuildwheel `test-command` used
  single-quoted `-m 'not crossproc_slow'`; `cmd.exe` does not strip single
  quotes, so pytest received literal-quote characters and exited with code 4
  (usage error). Changed to double quotes which both `sh` and `cmd.exe` handle
  correctly.
- **aarch64 QEMU test-skip**: cross-process timing tests (`test_crossproc_*`)
  are unreliable under QEMU emulation on x86_64 runners (subprocess startup
  10–20× slower than native). aarch64 wheels are now built but not tested
  under QEMU; they are identical to the natively verified x86_64 build.

## 1.0.1 — 2026-06-03

### Fixed
- **Windows build**: `gb_atomics.h` now uses `volatile` + `_ReadWriteBarrier`
  for MSVC; the C11 `<stdatomic.h>` header only works with clang-cl, not the
  native MSVC compiler. All four Windows Python versions now build and pass.
- **`writer_alive` cross-process bug (macOS 3.9 / ARM64)**: heartbeat was
  stored with `time.monotonic_ns()` which has a per-process epoch on Python 3.9
  macOS ARM64, causing the reader to always see the writer as dead.
  Switched to `time.time_ns()` (wall-clock Unix epoch), which is consistent
  across all processes on the same machine.
- **`test_crossproc_writer_death` timing**: replaced a fixed 1.5 s sleep with a
  10 s poll loop so slow process starts (Python 3.9 macOS notarisation) don't
  flake.
- **PyPI package name**: renamed from `GlobalBuffer` to `global_buffer` for PEP
  508 compliance; pre-built wheels for CPython 3.9–3.13 on Linux x86_64/aarch64,
  macOS x86_64/arm64, and Windows amd64 are now published.

## 1.0.0 — 2026-06-02

First stable release.

### Features
- Cross-process named shared-memory buffer with last-value (`latest`) and
  no-drop in-order (`next`) read semantics.
- **Array streams** — fixed dtype/shape numpy data, zero-copy writes via
  `reserve()`.
- **Message streams** — `pydantic` models on the public API, `msgspec` (msgpack)
  on the wire.
- Lock-free, tear-free single-writer / multi-reader ring: `capacity + 1` spare
  slot plus a per-slot seqlock built on C11 atomics (Cython `_core`).
- Background callbacks via `on_data()` and the subclassable `Consumer`.
- Near-0-CPU wakeups via adaptive polling of the shared commit counter; the poll
  backoff is tunable per reader with `poll_min` / `poll_max`.
- Heartbeat-based `reader.writer_alive`; `overruns` accounting; reader
  introspection (`shape` / `dtype` / `nbytes`).
- Explicit lifecycle (`close` / `unlink` / `gb.unlink(name)`); opts out of the
  multiprocessing `resource_tracker`.
- Benchmark/showcase examples (`writer.py`, `reader.py`) plus focused examples.
- Packaging: Cython build, cibuildwheel config, Docker + compose, CI matrix.

### Verified
- 70 tests pass on macOS / CPython 3.14, including a cross-process
  no-torn-reads stress test. Wheel builds and installs into a clean environment.

### Known limitations
- Broad CI verification on Linux / Windows / aarch64 (Jetson) is pending; wheels
  and workflows are configured but not yet exercised in this release.
- Reads copy out of shared memory; read-side zero-copy primitives exist in the
  core (`read_view_info` / `validate`) but are not wired into the reader yet.
- Notification is adaptive polling; a true 0-CPU kernel-blocking backend
  (eventfd / process-shared condvar / Windows semaphore) is planned.
- Single-writer per buffer is by design; `create()` guards with `BufferExists`
  but misuse is not otherwise prevented. No access control on segments.
