import numpy as np
from global_buffer import layout, _core


def make_array_buf(n_slots=4, slot_size=64):
    g = layout.geometry(layout.KIND_ARRAY, n_slots, slot_size)
    buf = bytearray(g["total_size"])
    layout.write_array_header(buf, n_slots=n_slots, slot_size=slot_size,
                              dtype="uint8", shape=(slot_size,))
    return buf, g, n_slots, slot_size


def test_commit_and_read_latest():
    buf, g, n_slots, slot_size = make_array_buf()
    payload = bytes(range(10))
    seq = _core.commit_copy(buf, payload, len(payload))
    assert seq == 0
    out, rseq, length = _core.read_latest(buf)
    assert rseq == 0 and length == 10
    assert bytes(out[:10]) == payload


def test_latest_count_increments():
    buf, *_ = make_array_buf()
    for i in range(5):
        seq = _core.commit_copy(buf, bytes([i]), 1)
        assert seq == i
    out, rseq, length = _core.read_latest(buf)
    assert rseq == 4 and out[0] == 4
    assert _core.latest_count(buf) == 5


def test_read_latest_empty_returns_none():
    buf, *_ = make_array_buf()
    assert _core.read_latest(buf) is None


def test_next_consumes_in_order():
    buf, g, n_slots, slot_size = make_array_buf()
    for i in range(3):
        _core.commit_copy(buf, bytes([i]), 1)
    cursor = 0
    seen = []
    while True:
        r = _core.read_next(buf, cursor)
        if r is None:
            break
        out, rseq, length, new_cursor, overruns = r
        seen.append(out[0])
        cursor = new_cursor
    assert seen == [0, 1, 2]


def test_next_overrun_when_lapped():
    buf, g, n_slots, slot_size = make_array_buf(n_slots=4)  # capacity 3
    for i in range(10):
        _core.commit_copy(buf, bytes([i]), 1)
    out, rseq, length, new_cursor, overruns = _core.read_next(buf, 0)
    assert rseq == 7 and overruns == 7  # oldest = 10 - 3
    assert out[0] == 7


def test_reserve_in_place():
    buf, g, n_slots, slot_size = make_array_buf()
    idx, payload_abs_off = _core.reserve_begin(buf)
    mv = memoryview(buf)
    arr = np.frombuffer(mv, dtype=np.uint8, count=slot_size, offset=payload_abs_off)
    arr[:4] = np.array([9, 8, 7, 6], dtype=np.uint8)
    seq = _core.reserve_commit(buf, idx, 4)
    assert seq == 0
    out, rseq, length = _core.read_latest(buf)
    assert length == 4 and list(out[:4]) == [9, 8, 7, 6]


def test_view_info_and_validate():
    buf, g, n_slots, slot_size = make_array_buf(n_slots=4)
    _core.commit_copy(buf, bytes([1]), 1)
    seq, off, length, new_cursor, overruns = _core.read_view_info(buf, 0, 1)
    assert seq == 0 and length == 1
    assert _core.validate(buf, 0) is True
    # overwrite slot 0 by lapping past it
    for i in range(8):
        _core.commit_copy(buf, bytes([i]), 1)
    assert _core.validate(buf, 0) is False


def test_heartbeat():
    buf, *_ = make_array_buf()
    _core.set_writer_heartbeat(buf, 12345)
    assert _core.get_writer_heartbeat(buf) == 12345
