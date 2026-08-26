# cython: language_level=3, boundscheck=False, wraparound=False
from cpython.buffer cimport (PyObject_GetBuffer, PyBuffer_Release,
                             Py_buffer, PyBUF_WRITABLE, PyBUF_SIMPLE)
from libc.stdint cimport uint32_t, uint64_t

cdef extern from "gb_atomics.h":
    uint64_t gb_load_u64(void *p) nogil
    void gb_store_u64(void *p, uint64_t v) nogil
    uint32_t gb_load_u32(void *p) nogil
    void gb_store_u32(void *p, uint32_t v) nogil
    void gb_memcpy(void *dst, const void *src, size_t n) nogil

# Header offsets (must match layout.py)
cdef enum:
    O_NSLOTS = 12
    O_SLOT_STRIDE = 16
    O_SLOT_SIZE = 24
    O_PAYLOAD_OFF = 32
    O_LATEST_COUNT = 40
    O_WRITER_HB = 56
    O_SLOTS_OFF = 72
    S_LOCK = 0
    S_SEQ = 8
    S_LENGTH = 16


cdef inline unsigned char* _base(object buf, Py_buffer* view) except NULL:
    if PyObject_GetBuffer(buf, view, PyBUF_WRITABLE | PyBUF_SIMPLE) != 0:
        raise BufferError("buffer is not writable / contiguous")
    return <unsigned char*> view.buf


cdef inline uint64_t _u64(unsigned char* base, Py_ssize_t off) nogil:
    return (<uint64_t*>(base + off))[0]


cdef inline uint32_t _u32(unsigned char* base, Py_ssize_t off) nogil:
    return (<uint32_t*>(base + off))[0]


cdef inline Py_ssize_t _slot_off(unsigned char* base, uint64_t idx) nogil:
    cdef uint64_t slots_off = _u64(base, O_SLOTS_OFF)
    cdef uint64_t stride = _u64(base, O_SLOT_STRIDE)
    return <Py_ssize_t>(slots_off + idx * stride)


cdef uint64_t _do_commit(unsigned char* base, unsigned char* src,
                         Py_ssize_t length) nogil:
    cdef uint64_t n_slots = _u32(base, O_NSLOTS)
    cdef uint64_t slot_size = _u64(base, O_SLOT_SIZE)
    cdef uint64_t payload_off = _u32(base, O_PAYLOAD_OFF)
    cdef uint64_t count = gb_load_u64(base + O_LATEST_COUNT)
    cdef uint64_t seq = count
    cdef uint64_t idx = seq % n_slots
    cdef Py_ssize_t soff = _slot_off(base, idx)
    cdef uint32_t lock = gb_load_u32(base + soff + S_LOCK)
    gb_store_u32(base + soff + S_LOCK, lock + 1)        # odd = writing
    if <uint64_t>length > slot_size:
        length = <Py_ssize_t>slot_size
    gb_memcpy(base + soff + payload_off, src, length)
    gb_store_u32(base + soff + S_LENGTH, <uint32_t>length)
    gb_store_u64(base + soff + S_SEQ, seq)
    gb_store_u32(base + soff + S_LOCK, lock + 2)        # even = stable
    gb_store_u64(base + O_LATEST_COUNT, count + 1)      # publish
    return seq


cdef uint64_t _do_commit_cached(unsigned char* base, uint64_t n_slots,
                                uint64_t slot_size, uint64_t payload_off,
                                uint64_t slots_off, uint64_t stride,
                                unsigned char* src, Py_ssize_t length,
                                uint64_t heartbeat) noexcept nogil:
    """Commit using immutable geometry cached by BoundBuffer.

    The public compatibility functions below still acquire a Python buffer on
    every call.  Reader/writer handles use BoundBuffer instead, so the hot path
    does not repeatedly create/release Py_buffer exports or reread header
    geometry from shared memory.
    """
    cdef uint64_t count = gb_load_u64(base + O_LATEST_COUNT)
    cdef uint64_t seq = count
    cdef uint64_t idx = seq % n_slots
    cdef Py_ssize_t soff = <Py_ssize_t>(slots_off + idx * stride)
    cdef uint32_t lock = gb_load_u32(base + soff + S_LOCK)
    if <uint64_t>length > slot_size:
        length = <Py_ssize_t>slot_size
    gb_store_u32(base + soff + S_LOCK, lock + 1)
    gb_memcpy(base + soff + payload_off, src, length)
    gb_store_u32(base + soff + S_LENGTH, <uint32_t>length)
    gb_store_u64(base + soff + S_SEQ, seq)
    gb_store_u32(base + soff + S_LOCK, lock + 2)
    gb_store_u64(base + O_LATEST_COUNT, count + 1)
    if heartbeat != 0:
        gb_store_u64(base + O_WRITER_HB, heartbeat)
    return seq


cdef object _read_latest_cached(unsigned char* base, uint64_t n_slots,
                                uint64_t payload_off, uint64_t slots_off,
                                uint64_t stride):
    cdef uint64_t count, seq, idx
    cdef Py_ssize_t soff
    cdef uint32_t l1, l2, length
    cdef bytes out
    cdef int tries
    for tries in range(64):
        count = gb_load_u64(base + O_LATEST_COUNT)
        if count == 0:
            return None
        seq = count - 1
        idx = seq % n_slots
        soff = <Py_ssize_t>(slots_off + idx * stride)
        l1 = gb_load_u32(base + soff + S_LOCK)
        if l1 & 1:
            continue
        length = gb_load_u32(base + soff + S_LENGTH)
        out = (<unsigned char*>(base + soff + payload_off))[:length]
        l2 = gb_load_u32(base + soff + S_LOCK)
        if l1 == l2 and gb_load_u64(base + soff + S_SEQ) == seq:
            return (out, seq, length)
    return None


cdef object _read_next_cached(unsigned char* base, uint64_t n_slots,
                              uint64_t payload_off, uint64_t slots_off,
                              uint64_t stride, uint64_t cursor):
    cdef uint64_t count, capacity, oldest, seq, idx
    cdef uint64_t overruns = 0
    cdef Py_ssize_t soff
    cdef uint32_t l1, l2, length
    cdef bytes out
    cdef int tries
    count = gb_load_u64(base + O_LATEST_COUNT)
    if cursor >= count:
        return None
    capacity = n_slots - 1
    if count > capacity and cursor < count - capacity:
        oldest = count - capacity
        overruns = oldest - cursor
        cursor = oldest
    seq = cursor
    for tries in range(64):
        idx = seq % n_slots
        soff = <Py_ssize_t>(slots_off + idx * stride)
        l1 = gb_load_u32(base + soff + S_LOCK)
        if l1 & 1:
            continue
        length = gb_load_u32(base + soff + S_LENGTH)
        out = (<unsigned char*>(base + soff + payload_off))[:length]
        l2 = gb_load_u32(base + soff + S_LOCK)
        if l1 == l2 and gb_load_u64(base + soff + S_SEQ) == seq:
            return (out, seq, length, seq + 1, overruns)
    return None


cdef int _read_one_into_cached(unsigned char* base, uint64_t n_slots,
                               uint64_t payload_off, uint64_t slots_off,
                               uint64_t stride, uint64_t cursor,
                               unsigned char* dst, uint64_t dst_size,
                               uint64_t* out_seq, uint64_t* out_cursor,
                               uint64_t* out_overruns) noexcept nogil:
    """Copy one sample into caller-owned storage without allocating bytes.

    Return 1 for a sample, 0 for no sample/unstable slot, and -1 when the
    destination is too small.  The function is nogil so a batch reader can
    drain several samples without reacquiring the interpreter lock per copy.
    """
    cdef uint64_t count, capacity, oldest, seq, idx
    cdef uint64_t overruns = 0
    cdef Py_ssize_t soff
    cdef uint32_t l1, l2, length
    cdef int tries
    count = gb_load_u64(base + O_LATEST_COUNT)
    if cursor >= count:
        return 0
    capacity = n_slots - 1
    if count > capacity and cursor < count - capacity:
        oldest = count - capacity
        overruns = oldest - cursor
        cursor = oldest
    seq = cursor
    for tries in range(64):
        idx = seq % n_slots
        soff = <Py_ssize_t>(slots_off + idx * stride)
        l1 = gb_load_u32(base + soff + S_LOCK)
        if l1 & 1:
            continue
        length = gb_load_u32(base + soff + S_LENGTH)
        if <uint64_t>length > dst_size:
            return -1
        gb_memcpy(dst, base + soff + payload_off, length)
        l2 = gb_load_u32(base + soff + S_LOCK)
        if l1 == l2 and gb_load_u64(base + soff + S_SEQ) == seq:
            out_seq[0] = seq
            out_cursor[0] = seq + 1
            out_overruns[0] = overruns
            return 1
    return 0


cdef class BoundOutput:
    """Persistent writable view for allocation-free destination reads."""
    cdef Py_buffer _view
    cdef unsigned char* _base_ptr
    cdef Py_ssize_t _length
    cdef bint _held

    def __cinit__(self, object out):
        self._held = False
        self._base_ptr = NULL
        self._length = 0
        if PyObject_GetBuffer(out, &self._view,
                              PyBUF_WRITABLE | PyBUF_SIMPLE) != 0:
            raise BufferError("destination is not writable / contiguous")
        self._held = True
        self._base_ptr = <unsigned char*>self._view.buf
        self._length = self._view.len

    cdef inline void _check(self) except *:
        if not self._held:
            raise BufferError("bound destination is closed")

    def close(self):
        if self._held:
            PyBuffer_Release(&self._view)
            self._held = False
            self._base_ptr = NULL
            self._length = 0

    def __dealloc__(self):
        if self._held:
            PyBuffer_Release(&self._view)


cdef class BoundBuffer:
    """Persistent read-only view of one shared-memory segment.

    Keeping the Py_buffer and immutable geometry for the lifetime of a handle
    removes buffer-export and header-load overhead from every operation.  The
    owner must call close() before closing the underlying SharedMemory object.
    """
    cdef Py_buffer _view
    cdef unsigned char* _base_ptr
    cdef bint _held
    cdef uint64_t _n_slots
    cdef uint64_t _slot_size
    cdef uint64_t _payload_off
    cdef uint64_t _slots_off
    cdef uint64_t _stride

    def __cinit__(self, object buf):
        self._held = False
        self._base_ptr = NULL
        if PyObject_GetBuffer(buf, &self._view,
                              PyBUF_WRITABLE | PyBUF_SIMPLE) != 0:
            raise BufferError("buffer is not writable / contiguous")
        self._held = True
        self._base_ptr = <unsigned char*>self._view.buf
        self._n_slots = _u32(self._base_ptr, O_NSLOTS)
        self._slot_size = _u64(self._base_ptr, O_SLOT_SIZE)
        self._payload_off = _u32(self._base_ptr, O_PAYLOAD_OFF)
        self._slots_off = _u64(self._base_ptr, O_SLOTS_OFF)
        self._stride = _u64(self._base_ptr, O_SLOT_STRIDE)

    cdef inline void _check(self) except *:
        if not self._held:
            raise BufferError("bound shared-memory view is closed")

    def close(self):
        if self._held:
            PyBuffer_Release(&self._view)
            self._held = False
            self._base_ptr = NULL

    def __dealloc__(self):
        if self._held:
            PyBuffer_Release(&self._view)

    def commit_copy(self, object src, Py_ssize_t length,
                    uint64_t heartbeat=0):
        cdef Py_buffer sview
        cdef unsigned char* sp
        cdef uint64_t seq
        self._check()
        if PyObject_GetBuffer(src, &sview, PyBUF_SIMPLE) != 0:
            raise BufferError("src is not a simple buffer")
        try:
            sp = <unsigned char*>sview.buf
            with nogil:
                seq = _do_commit_cached(
                    self._base_ptr, self._n_slots, self._slot_size,
                    self._payload_off, self._slots_off, self._stride,
                    sp, length, heartbeat)
            return seq
        finally:
            PyBuffer_Release(&sview)

    def reserve_begin(self):
        cdef uint64_t count, seq, idx
        cdef Py_ssize_t soff
        cdef uint32_t lock
        self._check()
        count = gb_load_u64(self._base_ptr + O_LATEST_COUNT)
        seq = count
        idx = seq % self._n_slots
        soff = <Py_ssize_t>(self._slots_off + idx * self._stride)
        lock = gb_load_u32(self._base_ptr + soff + S_LOCK)
        gb_store_u32(self._base_ptr + soff + S_LOCK, lock + 1)
        return (idx, <Py_ssize_t>(soff + self._payload_off))

    def reserve_commit(self, uint64_t idx, Py_ssize_t length,
                       uint64_t heartbeat=0):
        cdef uint64_t count, seq
        cdef Py_ssize_t soff
        cdef uint32_t lock
        self._check()
        count = gb_load_u64(self._base_ptr + O_LATEST_COUNT)
        seq = count
        soff = <Py_ssize_t>(self._slots_off + idx * self._stride)
        if <uint64_t>length > self._slot_size:
            length = <Py_ssize_t>self._slot_size
        gb_store_u32(self._base_ptr + soff + S_LENGTH, <uint32_t>length)
        gb_store_u64(self._base_ptr + soff + S_SEQ, seq)
        lock = gb_load_u32(self._base_ptr + soff + S_LOCK)
        gb_store_u32(self._base_ptr + soff + S_LOCK, lock + 1)
        gb_store_u64(self._base_ptr + O_LATEST_COUNT, count + 1)
        if heartbeat != 0:
            gb_store_u64(self._base_ptr + O_WRITER_HB, heartbeat)
        return seq

    def read_latest(self):
        self._check()
        return _read_latest_cached(self._base_ptr, self._n_slots,
                                   self._payload_off, self._slots_off,
                                   self._stride)

    def read_next(self, uint64_t cursor):
        self._check()
        return _read_next_cached(self._base_ptr, self._n_slots,
                                 self._payload_off, self._slots_off,
                                 self._stride, cursor)

    def read_next_into(self, object out, uint64_t cursor):
        """Copy one array sample into caller-owned contiguous storage."""
        cdef Py_buffer dview
        cdef int status
        cdef uint64_t seq, new_cursor, overruns
        self._check()
        if PyObject_GetBuffer(out, &dview,
                              PyBUF_WRITABLE | PyBUF_SIMPLE) != 0:
            raise BufferError("destination is not writable / contiguous")
        try:
            with nogil:
                status = _read_one_into_cached(
                    self._base_ptr, self._n_slots, self._payload_off,
                    self._slots_off, self._stride, cursor,
                    <unsigned char*>dview.buf, <uint64_t>dview.len,
                    &seq, &new_cursor, &overruns)
            if status < 0:
                raise ValueError("destination is smaller than the sample")
            if status == 0:
                return None
            return (seq, new_cursor, overruns)
        finally:
            PyBuffer_Release(&dview)

    def read_next_into_bound(self, BoundOutput out, uint64_t cursor):
        """Copy one sample into a persistent bound destination."""
        cdef int status
        cdef uint64_t seq, new_cursor, overruns
        self._check()
        out._check()
        with nogil:
            status = _read_one_into_cached(
                self._base_ptr, self._n_slots, self._payload_off,
                self._slots_off, self._stride, cursor,
                out._base_ptr, <uint64_t>out._length,
                &seq, &new_cursor, &overruns)
        if status < 0:
            raise ValueError("destination is smaller than the sample")
        if status == 0:
            return None
        return (seq, new_cursor, overruns)

    def read_next_batch_into(self, object out, uint64_t cursor,
                             uint64_t item_size, uint64_t max_items):
        """Drain up to ``max_items`` fixed-size samples into one array."""
        cdef Py_buffer dview
        cdef uint64_t i = 0
        cdef uint64_t cur = cursor
        cdef uint64_t seq, new_cursor, overruns
        cdef uint64_t total_overruns = 0
        cdef int status
        self._check()
        if max_items == 0 or item_size == 0:
            raise ValueError("max_items and item_size must be positive")
        if PyObject_GetBuffer(out, &dview,
                              PyBUF_WRITABLE | PyBUF_SIMPLE) != 0:
            raise BufferError("destination is not writable / contiguous")
        try:
            if <uint64_t>dview.len < item_size * max_items:
                raise ValueError("destination is smaller than max_items samples")
            with nogil:
                while i < max_items:
                    status = _read_one_into_cached(
                        self._base_ptr, self._n_slots, self._payload_off,
                        self._slots_off, self._stride, cur,
                        (<unsigned char*>dview.buf) + i * item_size,
                        item_size, &seq, &new_cursor, &overruns)
                    if status != 1:
                        break
                    cur = new_cursor
                    total_overruns += overruns
                    i += 1
            if status < 0:
                raise ValueError("destination item is smaller than the sample")
            if i == 0:
                return None
            return (i, cur, total_overruns)
        finally:
            PyBuffer_Release(&dview)

    def read_next_batch_into_bound(self, BoundOutput out, uint64_t cursor,
                                   uint64_t item_size, uint64_t max_items):
        """Drain into one persistent bound destination."""
        cdef uint64_t i = 0
        cdef uint64_t cur = cursor
        cdef uint64_t seq, new_cursor, overruns
        cdef uint64_t total_overruns = 0
        cdef int status = 0
        self._check()
        out._check()
        if max_items == 0 or item_size == 0:
            raise ValueError("max_items and item_size must be positive")
        if <uint64_t>out._length < item_size * max_items:
            raise ValueError("destination is smaller than max_items samples")
        with nogil:
            while i < max_items:
                status = _read_one_into_cached(
                    self._base_ptr, self._n_slots, self._payload_off,
                    self._slots_off, self._stride, cur,
                    out._base_ptr + i * item_size, item_size,
                    &seq, &new_cursor, &overruns)
                if status != 1:
                    break
                cur = new_cursor
                total_overruns += overruns
                i += 1
        if status < 0:
            raise ValueError("destination item is smaller than the sample")
        if i == 0:
            return None
        return (i, cur, total_overruns)

    def latest_count(self):
        self._check()
        return gb_load_u64(self._base_ptr + O_LATEST_COUNT)

    def set_writer_heartbeat(self, uint64_t v):
        self._check()
        gb_store_u64(self._base_ptr + O_WRITER_HB, v)

    def get_writer_heartbeat(self):
        self._check()
        return gb_load_u64(self._base_ptr + O_WRITER_HB)


def bind(object buf):
    return BoundBuffer(buf)


def bind_output(object out):
    return BoundOutput(out)


def commit_copy(object buf, object src, Py_ssize_t length):
    """Copy `length` bytes from src into the next slot; publish. Returns seq."""
    cdef Py_buffer view, sview
    cdef unsigned char* base = _base(buf, &view)
    cdef unsigned char* sp
    try:
        if PyObject_GetBuffer(src, &sview, PyBUF_SIMPLE) != 0:
            raise BufferError("src is not a simple buffer")
        try:
            sp = <unsigned char*> sview.buf
            return _do_commit(base, sp, length)
        finally:
            PyBuffer_Release(&sview)
    finally:
        PyBuffer_Release(&view)


def reserve_begin(object buf):
    """Raise the next slot's lock; return (slot_idx, absolute_payload_offset)."""
    cdef Py_buffer view
    cdef unsigned char* base = _base(buf, &view)
    cdef uint64_t n_slots, count, seq, idx, payload_off
    cdef Py_ssize_t soff
    cdef uint32_t lock
    try:
        n_slots = _u32(base, O_NSLOTS)
        payload_off = _u32(base, O_PAYLOAD_OFF)
        count = gb_load_u64(base + O_LATEST_COUNT)
        seq = count
        idx = seq % n_slots
        soff = _slot_off(base, idx)
        lock = gb_load_u32(base + soff + S_LOCK)
        gb_store_u32(base + soff + S_LOCK, lock + 1)    # writing
        return (idx, <Py_ssize_t>(soff + payload_off))
    finally:
        PyBuffer_Release(&view)


def reserve_commit(object buf, uint64_t idx, Py_ssize_t length):
    """Finalize reserve_begin: set length+seq, lower lock, publish. Returns seq."""
    cdef Py_buffer view
    cdef unsigned char* base = _base(buf, &view)
    cdef uint64_t count, seq, slot_size
    cdef Py_ssize_t soff
    cdef uint32_t lock
    try:
        slot_size = _u64(base, O_SLOT_SIZE)
        count = gb_load_u64(base + O_LATEST_COUNT)
        seq = count
        soff = _slot_off(base, idx)
        if <uint64_t>length > slot_size:
            length = <Py_ssize_t>slot_size
        gb_store_u32(base + soff + S_LENGTH, <uint32_t>length)
        gb_store_u64(base + soff + S_SEQ, seq)
        lock = gb_load_u32(base + soff + S_LOCK)
        gb_store_u32(base + soff + S_LOCK, lock + 1)    # back to even
        gb_store_u64(base + O_LATEST_COUNT, count + 1)
        return seq
    finally:
        PyBuffer_Release(&view)


def read_latest(object buf):
    """Return (bytes_copy, seq, length) of newest sample, or None if empty."""
    cdef Py_buffer view
    cdef unsigned char* base = _base(buf, &view)
    cdef uint64_t n_slots, count, seq, idx, payload_off, slots_off, stride
    cdef Py_ssize_t soff
    cdef uint32_t l1, l2, length
    cdef bytes out
    cdef int tries
    try:
        n_slots = _u32(base, O_NSLOTS)
        payload_off = _u32(base, O_PAYLOAD_OFF)
        slots_off = _u64(base, O_SLOTS_OFF)
        stride = _u64(base, O_SLOT_STRIDE)
        for tries in range(64):
            count = gb_load_u64(base + O_LATEST_COUNT)
            if count == 0:
                return None
            seq = count - 1
            idx = seq % n_slots
            soff = <Py_ssize_t>(slots_off + idx * stride)
            l1 = gb_load_u32(base + soff + S_LOCK)
            if l1 & 1:
                continue
            length = gb_load_u32(base + soff + S_LENGTH)
            out = (<unsigned char*>(base + soff + payload_off))[:length]
            l2 = gb_load_u32(base + soff + S_LOCK)
            if l1 == l2 and gb_load_u64(base + soff + S_SEQ) == seq:
                return (out, seq, length)
        return None
    finally:
        PyBuffer_Release(&view)


def read_next(object buf, uint64_t cursor):
    """Read sample at `cursor`. Returns (bytes, seq, length, new_cursor, overruns)
    or None if no sample >= cursor is available yet."""
    cdef Py_buffer view
    cdef unsigned char* base = _base(buf, &view)
    cdef uint64_t n_slots, count, capacity, oldest, seq, idx, payload_off
    cdef uint64_t slots_off, stride
    cdef uint64_t overruns = 0
    cdef Py_ssize_t soff
    cdef uint32_t l1, l2, length
    cdef bytes out
    cdef int tries
    try:
        count = gb_load_u64(base + O_LATEST_COUNT)
        if cursor >= count:
            return None
        n_slots = _u32(base, O_NSLOTS)
        capacity = n_slots - 1
        payload_off = _u32(base, O_PAYLOAD_OFF)
        slots_off = _u64(base, O_SLOTS_OFF)
        stride = _u64(base, O_SLOT_STRIDE)
        if count > capacity and cursor < count - capacity:
            oldest = count - capacity
            overruns = oldest - cursor
            cursor = oldest
        seq = cursor
        for tries in range(64):
            idx = seq % n_slots
            soff = <Py_ssize_t>(slots_off + idx * stride)
            l1 = gb_load_u32(base + soff + S_LOCK)
            if l1 & 1:
                continue
            length = gb_load_u32(base + soff + S_LENGTH)
            out = (<unsigned char*>(base + soff + payload_off))[:length]
            l2 = gb_load_u32(base + soff + S_LOCK)
            if l1 == l2 and gb_load_u64(base + soff + S_SEQ) == seq:
                return (out, seq, length, seq + 1, overruns)
        return None
    finally:
        PyBuffer_Release(&view)


def read_view_info(object buf, uint64_t cursor, int latest):
    """Zero-copy read: return (seq, payload_abs_off, length, new_cursor, overruns)
    without copying, or None. Caller must call validate(buf, seq) after use."""
    cdef Py_buffer view
    cdef unsigned char* base = _base(buf, &view)
    cdef uint64_t n_slots, count, capacity, oldest, seq, idx, payload_off
    cdef uint64_t overruns = 0
    cdef Py_ssize_t soff
    cdef uint32_t length
    try:
        count = gb_load_u64(base + O_LATEST_COUNT)
        if count == 0 or (not latest and cursor >= count):
            return None
        n_slots = _u32(base, O_NSLOTS)
        capacity = n_slots - 1
        payload_off = _u32(base, O_PAYLOAD_OFF)
        if latest:
            seq = count - 1
        else:
            if count > capacity and cursor < count - capacity:
                oldest = count - capacity
                overruns = oldest - cursor
                cursor = oldest
            seq = cursor
        idx = seq % n_slots
        soff = _slot_off(base, idx)
        length = gb_load_u32(base + soff + S_LENGTH)
        return (seq, <Py_ssize_t>(soff + payload_off), length, seq + 1, overruns)
    finally:
        PyBuffer_Release(&view)


def validate(object buf, uint64_t seq):
    """True if the slot holding `seq` still holds it and is stable (not torn /
    not overwritten). Used after a zero-copy view read."""
    cdef Py_buffer view
    cdef unsigned char* base = _base(buf, &view)
    cdef uint64_t n_slots, idx
    cdef Py_ssize_t soff
    cdef uint32_t lock
    try:
        n_slots = _u32(base, O_NSLOTS)
        idx = seq % n_slots
        soff = _slot_off(base, idx)
        lock = gb_load_u32(base + soff + S_LOCK)
        if lock & 1:
            return False
        return gb_load_u64(base + soff + S_SEQ) == seq
    finally:
        PyBuffer_Release(&view)


def latest_count(object buf):
    cdef Py_buffer view
    cdef unsigned char* base = _base(buf, &view)
    try:
        return gb_load_u64(base + O_LATEST_COUNT)
    finally:
        PyBuffer_Release(&view)


def set_writer_heartbeat(object buf, uint64_t v):
    cdef Py_buffer view
    cdef unsigned char* base = _base(buf, &view)
    try:
        gb_store_u64(base + O_WRITER_HB, v)
    finally:
        PyBuffer_Release(&view)


def get_writer_heartbeat(object buf):
    cdef Py_buffer view
    cdef unsigned char* base = _base(buf, &view)
    try:
        return gb_load_u64(base + O_WRITER_HB)
    finally:
        PyBuffer_Release(&view)


def _selftest():
    return 42
