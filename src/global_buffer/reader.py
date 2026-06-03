import threading
import time

import numpy as np

from . import _core, layout
from .buffer import _ShmHandle, open_shm, shm_name
from .codec import MessageCodec
from .exceptions import BufferNotFound, Empty, SchemaMismatch
from .notifier import wait_for_count
from .spec import model_schema_bytes

WRITER_TIMEOUT_NS = 2_000_000_000  # 2 s without heartbeat -> writer dead


class _CallbackHandle:
    def __init__(self, reader, fn, mode):
        self._reader = reader
        self._fn = fn
        self._mode = mode
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        r = self._reader
        buf = r._shm.buf
        get_count = lambda: _core.latest_count(buf)   # bound once, not per loop
        last = r._cursor
        while not self._stop.is_set():
            new = wait_for_count(get_count, last, timeout=0.2,
                                 stop=self._stop.is_set)
            if self._stop.is_set():
                break
            if new is None:
                continue  # timeout; loop to re-check stop
            if self._mode == "latest":
                res = r._read_latest_raw()
                if res is not None:
                    self._fn(*res)
                last = new
            else:
                while not self._stop.is_set():
                    res = r._read_next_raw()
                    if res is None:
                        break
                    self._fn(*res)
                last = r._cursor

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2.0)


class Reader(_ShmHandle):
    """Reader handle attached to a named buffer. Created with
    :func:`global_buffer.attach`."""

    _role = "reader"

    def __init__(self, name, model=None):
        self.name = name
        self._closed = False
        self.overruns = 0
        try:
            self._shm = open_shm(shm_name(name))
        except FileNotFoundError:
            raise BufferNotFound(f"no buffer named {name!r}")

        self._header = layout.read_header(self._shm.buf)
        if self._header["magic"] != layout.MAGIC:
            self._shm.close()
            raise SchemaMismatch(f"bad magic for {name!r}")
        if self._header["version"] != layout.VERSION:
            self._shm.close()
            raise SchemaMismatch(
                f"version {self._header['version']} != {layout.VERSION}")

        self.kind = self._header["kind"]
        if self.kind == layout.KIND_ARRAY:
            self._dtype = np.dtype(self._header["dtype"])
            self._shape = self._header["shape"]
            self._codec = None
        else:
            if model is not None:
                raw = model_schema_bytes(model)
                if layout.schema_hash(raw) != self._header["schema_hash"]:
                    self._shm.close()
                    raise SchemaMismatch(
                        f"model {model.__name__} does not match buffer {name!r}")
            self._codec = MessageCodec(model, validate=model is not None)

        # start consuming from the newest sample present at attach time
        self._cursor = _core.latest_count(self._shm.buf)

    # ---- decode ----
    def _decode(self, payload):
        if self.kind == layout.KIND_ARRAY:
            return np.frombuffer(payload, dtype=self._dtype).reshape(self._shape)
        return self._codec.decode(payload)

    def _read_latest_raw(self):
        res = _core.read_latest(self._shm.buf)
        if res is None:
            return None
        payload, seq, length = res
        return self._decode(payload), seq

    def _read_next_raw(self):
        res = _core.read_next(self._shm.buf, self._cursor)
        if res is None:
            return None
        payload, seq, length, new_cursor, overruns = res
        self.overruns += overruns
        self._cursor = new_cursor
        return self._decode(payload), seq

    # ---- public read API ----
    def latest(self):
        """Return the newest committed sample, or None if the buffer is empty."""
        self._check()
        res = self._read_latest_raw()
        return None if res is None else res[0]

    def next(self, timeout=None):
        """Return the next unconsumed sample in order, blocking up to ``timeout``
        seconds. Raises :class:`Empty` on timeout."""
        self._check()
        deadline = None if timeout is None else time.monotonic() + timeout
        get_count = lambda: _core.latest_count(self._shm.buf)
        while True:
            res = self._read_next_raw()
            if res is not None:
                return res[0]
            if deadline is None:
                wait_for_count(get_count, self._cursor, timeout=0.2)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Empty(f"no sample within {timeout}s")
            wait_for_count(get_count, self._cursor, timeout=remaining)

    def on_data(self, fn, mode="latest"):
        """Invoke ``fn(sample, seq)`` on a background thread as samples arrive."""
        self._check()
        if mode not in ("latest", "next"):
            raise ValueError("mode must be 'latest' or 'next'")
        return _CallbackHandle(self, fn, mode)

    @property
    def shape(self):
        """Declared array shape (None for message buffers)."""
        return getattr(self, "_shape", None) if self.kind == layout.KIND_ARRAY else None

    @property
    def dtype(self):
        """Declared numpy dtype (None for message buffers)."""
        return getattr(self, "_dtype", None) if self.kind == layout.KIND_ARRAY else None

    @property
    def nbytes(self):
        """Bytes per array sample (None for message buffers)."""
        if self.kind != layout.KIND_ARRAY:
            return None
        n = self._dtype.itemsize
        for d in self._shape:
            n *= d
        return n

    @property
    def writer_alive(self):
        hb = _core.get_writer_heartbeat(self._shm.buf)
        if hb == 0:
            return False
        return (time.monotonic_ns() - hb) < WRITER_TIMEOUT_NS
