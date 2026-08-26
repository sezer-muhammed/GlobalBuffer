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
        get_count = r._bound.latest_count
        last = r._cursor
        while not self._stop.is_set():
            new = wait_for_count(get_count, last, timeout=0.2,
                                 stop=self._stop.is_set,
                                 min_interval=r._poll_min,
                                 max_interval=r._poll_max)
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

    def __init__(self, name, model=None, poll_min=None, poll_max=None):
        self.name = name
        self._closed = False
        self.overruns = 0
        self._poll_min = poll_min   # poll backoff floor (s); None -> Poller default
        self._poll_max = poll_max   # poll backoff cap (s); raise it to cut idle CPU
                                    # for many readers, at the cost of wake latency
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
            msg_codec = self._header.get("msg_codec",
                                        layout.MSG_CODEC_MSGPACK)
            if msg_codec not in (layout.MSG_CODEC_MSGPACK,
                                 layout.MSG_CODEC_PROTOBUF):
                self._shm.close()
                raise SchemaMismatch(
                    f"unsupported message codec {msg_codec} for {name!r}")
            if model is not None:
                raw = model_schema_bytes(model)
                if layout.schema_hash(raw) != self._header["schema_hash"]:
                    self._shm.close()
                    raise SchemaMismatch(
                        f"model {model.__name__} does not match buffer {name!r}")
            codec_name = ("protobuf" if msg_codec == layout.MSG_CODEC_PROTOBUF
                          else "msgpack")
            self._codec = MessageCodec(model, validate=model is not None,
                                       codec=codec_name)

        # start consuming from the newest sample present at attach time
        self._bound = _core.bind(self._shm.buf)
        self._cursor = self._bound.latest_count()

    # ---- decode ----
    def _decode(self, payload):
        if self.kind == layout.KIND_ARRAY:
            return np.frombuffer(payload, dtype=self._dtype).reshape(self._shape)
        return self._codec.decode(payload)

    def _validate_array_destination(self, out, batch=False):
        if self.kind != layout.KIND_ARRAY:
            raise TypeError("destination APIs are only valid for array buffers")
        if not isinstance(out, np.ndarray):
            raise TypeError("destination must be a numpy.ndarray")
        if out.dtype != self._dtype:
            raise ValueError(f"dtype {out.dtype} != declared {self._dtype}")
        expected = ((out.shape[0],) + self._shape) if batch else self._shape
        if out.shape != expected:
            raise ValueError(f"shape {out.shape} != declared {expected}")
        if not out.flags.c_contiguous or not out.flags.writeable:
            raise ValueError("destination must be writable and C-contiguous")

    def _bind_array_destination(self, out):
        current = getattr(self, "_into_output_obj", None)
        if current is not out:
            old = getattr(self, "_into_bound", None)
            if old is not None:
                old.close()
            self._into_output_obj = out
            self._into_bound = _core.bind_output(out)
        return self._into_bound

    def _read_latest_raw(self):
        res = self._bound.read_latest()
        if res is None:
            return None
        payload, seq, length = res
        return self._decode(payload), seq

    def _read_next_raw(self):
        res = self._bound.read_next(self._cursor)
        if res is None:
            return None
        payload, seq, length, new_cursor, overruns = res
        self.overruns += overruns
        self._cursor = new_cursor
        return self._decode(payload), seq

    def next_into(self, out, timeout=None):
        """Copy the next array sample into ``out`` without allocating bytes.

        Returns the sample sequence number. ``out`` is reused by the caller,
        so this API is suitable for allocation-free high-rate consumers.
        """
        self._check()
        self._validate_array_destination(out)
        destination = self._bind_array_destination(out)
        deadline = None if timeout is None else time.monotonic() + timeout
        get_count = self._bound.latest_count
        while True:
            res = self._bound.read_next_into_bound(destination, self._cursor)
            if res is not None:
                seq, new_cursor, overruns = res
                self.overruns += overruns
                self._cursor = new_cursor
                return seq
            if deadline is None:
                wait_for_count(get_count, self._cursor, timeout=0.2,
                               min_interval=self._poll_min,
                               max_interval=self._poll_max)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Empty(f"no sample within {timeout}s")
            wait_for_count(get_count, self._cursor, timeout=remaining,
                           min_interval=self._poll_min,
                           max_interval=self._poll_max)

    def next_batch_into(self, out, timeout=None):
        """Drain available array samples into a 2-D-or-higher output array.

        ``out.shape`` must be ``(batch_size,) + reader.shape``. Returns the
        number of samples copied and reuses the caller-owned storage.
        """
        self._check()
        if not isinstance(out, np.ndarray) or out.ndim < 1:
            raise TypeError("destination must be a numpy.ndarray with a batch axis")
        if out.shape[0] < 1:
            raise ValueError("destination batch size must be positive")
        self._validate_array_destination(out, batch=True)
        destination = self._bind_array_destination(out)
        deadline = None if timeout is None else time.monotonic() + timeout
        get_count = self._bound.latest_count
        item_size = self._dtype.itemsize
        for dim in self._shape:
            item_size *= dim
        while True:
            res = self._bound.read_next_batch_into_bound(
                destination, self._cursor, item_size, out.shape[0]
            )
            if res is not None:
                count, new_cursor, overruns = res
                self.overruns += overruns
                self._cursor = new_cursor
                return count
            if deadline is None:
                wait_for_count(get_count, self._cursor, timeout=0.2,
                               min_interval=self._poll_min,
                               max_interval=self._poll_max)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Empty(f"no sample within {timeout}s")
            wait_for_count(get_count, self._cursor, timeout=remaining,
                           min_interval=self._poll_min,
                           max_interval=self._poll_max)

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
        get_count = self._bound.latest_count
        while True:
            res = self._read_next_raw()
            if res is not None:
                return res[0]
            if deadline is None:
                wait_for_count(get_count, self._cursor, timeout=0.2,
                               min_interval=self._poll_min,
                               max_interval=self._poll_max)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Empty(f"no sample within {timeout}s")
            wait_for_count(get_count, self._cursor, timeout=remaining,
                           min_interval=self._poll_min,
                           max_interval=self._poll_max)

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
        hb = self._bound.get_writer_heartbeat()
        if hb == 0:
            return False
        return (time.time_ns() - hb) < WRITER_TIMEOUT_NS
