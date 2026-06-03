import inspect
import os
import time
from contextlib import contextmanager
from multiprocessing import shared_memory

import numpy as np

from . import _core, layout
from .codec import MessageCodec
from .exceptions import BufferClosed, BufferExists
from .spec import normalize_schema


def shm_name(name):
    return f"gb_{name}"


def _supports_track():
    try:
        return "track" in inspect.signature(shared_memory.SharedMemory).parameters
    except (TypeError, ValueError):
        return False


_TRACK = _supports_track()


def open_shm(name, create=False, size=0):
    """Open/create a shared-memory segment with the multiprocessing
    resource_tracker kept out of the way.

    GlobalBuffer manages segment lifetime explicitly via :meth:`GlobalBuffer.unlink`
    / :func:`global_buffer.unlink`, so the resource_tracker must never auto-unlink
    a segment out from under another process. On Python 3.13+ we pass
    ``track=False``; on older versions we unregister the segment immediately after
    opening. All tracker policy lives here so no other module has to think about it.
    """
    if _TRACK:
        if create:
            return shared_memory.SharedMemory(name=name, create=True, size=size,
                                              track=False)
        return shared_memory.SharedMemory(name=name, track=False)

    if create:
        shm = shared_memory.SharedMemory(name=name, create=True, size=size)
    else:
        shm = shared_memory.SharedMemory(name=name)
    try:
        from multiprocessing import resource_tracker
        resource_tracker.unregister(shm._name, "shared_memory")
    except Exception:
        pass
    return shm


class _ShmHandle:
    """Shared lifecycle for the writer and reader handles: a closable wrapper
    around one shared-memory segment, usable as a context manager."""

    name = None
    _role = "buffer"
    _closed = True
    _shm = None

    def _check(self):
        if self._closed:
            raise BufferClosed(f"{self._role} {self.name!r} is closed")

    def close(self):
        """Detach this handle. The segment itself survives until unlinked."""
        if self._closed:
            return
        self._closed = True
        self._shm.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class GlobalBuffer(_ShmHandle):
    """Writer/owner handle for a named shared-memory buffer.

    Single-writer, multi-reader. Created with :func:`global_buffer.create`.
    """

    _role = "buffer"

    def __init__(self, name, schema, capacity, max_bytes=None):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.name = name
        self._closed = False

        kind, info = normalize_schema(schema)
        self.kind = kind
        n_slots = capacity + 1  # spare slot so writer never lands on newest readable

        if kind == layout.KIND_ARRAY:
            self._spec = info["spec"]
            self._dtype = self._spec.np_dtype       # cache: avoid rebuilding per write
            self._shape = self._spec.shape
            slot_size = info["min_slot_size"]
            self._codec = None
        else:
            self._model = info["model"]
            slot_size = max_bytes or 4096
            self._codec = MessageCodec(info["model"], validate=True)
            self._schema_json = info["schema_json"]
            self._schema_hash = info["schema_hash"]

        g = layout.geometry(kind, n_slots, slot_size)
        try:
            self._shm = open_shm(shm_name(name), create=True, size=g["total_size"])
        except FileExistsError:
            raise BufferExists(f"buffer {name!r} already exists")

        buf = self._shm.buf
        if kind == layout.KIND_ARRAY:
            layout.write_array_header(buf, n_slots=n_slots, slot_size=slot_size,
                                      dtype=info["dtype"], shape=info["shape"])
        else:
            layout.write_msg_header(buf, n_slots=n_slots, slot_size=slot_size,
                                    schema_json=self._schema_json,
                                    schema_hash=self._schema_hash)
        self._n_slots = n_slots
        self._slot_size = slot_size
        self._geo = g
        layout.write_writer_pid(buf, os.getpid())
        self.heartbeat()

    # ---- writes ----
    def write(self, data):
        """Publish a single sample (numpy array or pydantic model / dict)."""
        self._check()
        if self.kind == layout.KIND_ARRAY:
            arr = np.ascontiguousarray(data, dtype=self._dtype)
            if arr.shape != self._shape:
                raise ValueError(f"shape {arr.shape} != declared {self._shape}")
            _core.commit_copy(self._shm.buf, arr, arr.nbytes)
        else:
            blob = self._codec.encode(data)
            if len(blob) > self._slot_size:
                raise ValueError(
                    f"encoded message {len(blob)}B exceeds max_bytes "
                    f"{self._slot_size}")
            _core.commit_copy(self._shm.buf, blob, len(blob))
        self.heartbeat()

    @contextmanager
    def reserve(self):
        """Zero-copy array write: yields an ndarray view into the target slot.

        Fill the view in place; the sample is published on context exit.
        """
        self._check()
        if self.kind != layout.KIND_ARRAY:
            raise TypeError("reserve() is only valid for array buffers")
        idx, payload_off = _core.reserve_begin(self._shm.buf)
        view = np.ndarray(self._shape, dtype=self._dtype,
                          buffer=self._shm.buf, offset=payload_off)
        try:
            yield view
        finally:
            _core.reserve_commit(self._shm.buf, idx, self._spec.nbytes)
            self.heartbeat()

    # ---- liveness ----
    def heartbeat(self):
        _core.set_writer_heartbeat(self._shm.buf, time.monotonic_ns())

    # ---- lifecycle ----
    def unlink(self):
        """Owner removes the segment from the system."""
        try:
            self._shm.unlink()
        except FileNotFoundError:
            pass
