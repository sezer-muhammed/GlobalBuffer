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
