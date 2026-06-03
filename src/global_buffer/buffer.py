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


class GlobalBuffer:
    """Writer/owner handle for a named shared-memory buffer.

    Single-writer, multi-reader. Created with :func:`global_buffer.create`.
    """

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
            self._shm = shared_memory.SharedMemory(
                name=shm_name(name), create=True, size=g["total_size"])
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
        buf[layout.O_WRITER_PID:layout.O_WRITER_PID + 8] = \
            os.getpid().to_bytes(8, "little")
        self.heartbeat()

    # ---- writes ----
    def write(self, data):
        """Publish a single sample (numpy array or pydantic model / dict)."""
        self._check()
        if self.kind == layout.KIND_ARRAY:
            arr = np.ascontiguousarray(data, dtype=self._spec.np_dtype)
            if arr.shape != self._spec.shape:
                raise ValueError(
                    f"shape {arr.shape} != declared {self._spec.shape}")
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
        view = np.ndarray(self._spec.shape, dtype=self._spec.np_dtype,
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
    def _check(self):
        if self._closed:
            raise BufferClosed(f"buffer {self.name!r} is closed")

    def close(self):
        """Detach this handle (segment stays alive until unlink())."""
        if self._closed:
            return
        self._closed = True
        self._shm.close()

    def unlink(self):
        """Owner removes the segment from the system."""
        try:
            self._shm.unlink()
        except FileNotFoundError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
