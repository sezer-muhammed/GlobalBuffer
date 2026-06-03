# GlobalBuffer Implementation Plan

**Goal:** Build `GlobalBuffer` (`import global_buffer as gb`): cross-platform, cross-process
named shared-memory buffer with last-value + no-drop-ring semantics, zero-copy numpy arrays
and pydantic/msgspec messages, 0-CPU blocking callbacks, compiled wheels. Local only — no push.

**Architecture:** One `multiprocessing.shared_memory` segment per named buffer: header +
reader registry + `capacity+1` ring slots. Cython `_core` (C11 atomics) owns the lock-free
hot path: per-slot seqlock + global commit counter for tear-free single-writer/multi-reader.
Python layer: schema handling, pydantic<->msgspec bridge, lifecycle/registry, cross-platform
`Notifier` (POSIX/Windows named semaphores, polling fallback).

**Tech:** Python 3.9-3.14, Cython, C11 (stdatomic.h), numpy, msgspec, pydantic v2, ctypes,
cibuildwheel + GitHub Actions, Docker.

See spec: docs/superpowers/specs/2026-06-02-globalbuffer-design.md

## Layout constants
- MAGIC=0x46554247 ("GBUF" LE), VERSION=1, KIND_ARRAY=1, KIND_MSG=2
- NDIM_MAX=8, MAX_READERS=64, HEADER_SIZE=4096, SLOT_ALIGN=64, SLOT_PAYLOAD_OFF=64
- Header: magic0 version4 kind8 n_slots12 slot_stride16(u64) slot_size24(u64)
  payload_off32 max_readers36 latest_count40(atomic u64) writer_pid48 writer_hb56(atomic u64)
  registry_off64 slots_off72 schema_hash80 schema_json_len88 dtype128(16s) ndim144 shape152(u64x8)
  schema_json256
- Registry entry 64B: pid0 reg_index8 cursor16 alive24(atomic u32) heartbeat32(atomic u64)
- Slot: lock0(atomic u32 even=stable/odd=writing) seq8(atomic u64) length16 payload@64
- slot_stride=align_up(64+slot_size,64); slots_off=align_up(4096+64*64,4096)
- Notifier name per reader idx i: "gb.<name>.<i>" (POSIX prefix /)

## Tasks
1. Scaffold + buildable Cython core (venv, gb_atomics.h, _core.pyx _selftest, setup.py,
   pyproject.toml, .gitignore, MANIFEST.in, LICENSE, __init__.py, conftest.py).
2. exceptions.py
3. layout.py (offsets, geometry, schema_hash, header pack/unpack)
4. spec.py (ArraySpec, normalize_schema)
5. _core.pyx (commit_copy/reserve/read_latest/read_next/read_view_info/validate/heartbeat)
6. codec.py (msgspec bridge)
7. notifier (posix/windows/poll + factory)
8. buffer.py GlobalBuffer writer
9. reader.py Reader
10. consumer.py Consumer
11. public API + gb.unlink
12. cross-process tests
13. examples
14. Docker
15. CI workflows
16. README + final verification

## Notes
- macOS lacks sem_timedwait -> trywait+0.5ms loop (near-0 CPU).
- signal() ignores semaphore overflow (saturated sem still wakes; drain self-corrects).
- Jetson/aarch64 smoke is hardware-manual.
- Deferred: GPU buffers, wait_all barrier.
