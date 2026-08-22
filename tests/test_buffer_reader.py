import numpy as np
import pydantic
import pytest

import global_buffer as gb
from global_buffer import _core


# ---- writer ----
def test_create_array_and_write(tmp_name):
    buf = gb.create(name=tmp_name, schema=gb.ArraySpec("float32", (4,)), capacity=4)
    buf.write(np.arange(4, dtype=np.float32))
    assert _core.latest_count(buf._shm.buf) == 1
    buf.close()
    buf.unlink()


def test_reserve_in_place(tmp_name):
    buf = gb.create(name=tmp_name, schema=gb.ArraySpec("uint8", (8,)), capacity=2)
    with buf.reserve() as slot:
        slot[:] = np.arange(8, dtype=np.uint8)
    assert _core.latest_count(buf._shm.buf) == 1
    buf.close()
    buf.unlink()


def test_create_duplicate_raises(tmp_name):
    buf = gb.create(name=tmp_name, schema=gb.ArraySpec("uint8", (8,)), capacity=2)
    with pytest.raises(gb.BufferExists):
        gb.create(name=tmp_name, schema=gb.ArraySpec("uint8", (8,)), capacity=2)
    buf.close()
    buf.unlink()


def test_write_wrong_shape_raises(tmp_name):
    buf = gb.create(name=tmp_name, schema=gb.ArraySpec("float32", (4,)), capacity=2)
    with pytest.raises(ValueError):
        buf.write(np.arange(5, dtype=np.float32))
    buf.close()
    buf.unlink()


def test_message_write(tmp_name):
    class M(pydantic.BaseModel):
        gain: float
        cam_on: bool

    buf = gb.create(name=tmp_name, schema=M, capacity=4, max_bytes=256)
    buf.write(M(gain=1.0, cam_on=True))
    assert _core.latest_count(buf._shm.buf) == 1
    buf.close()
    buf.unlink()


def test_message_too_large_raises(tmp_name):
    class M(pydantic.BaseModel):
        blob: str

    buf = gb.create(name=tmp_name, schema=M, capacity=2, max_bytes=32)
    with pytest.raises(ValueError):
        buf.write(M(blob="x" * 1000))
    buf.close()
    buf.unlink()


# ---- reader ----
def test_attach_array_latest(tmp_name):
    w = gb.create(name=tmp_name, schema=gb.ArraySpec("float32", (4,)), capacity=4)
    w.write(np.array([1, 2, 3, 4], dtype=np.float32))
    r = gb.attach(tmp_name)
    out = r.latest()
    assert np.array_equal(out, np.array([1, 2, 3, 4], dtype=np.float32))
    r.close()
    w.close()
    w.unlink()


def test_latest_empty_returns_none(tmp_name):
    w = gb.create(name=tmp_name, schema=gb.ArraySpec("float32", (4,)), capacity=4)
    r = gb.attach(tmp_name)
    assert r.latest() is None
    r.close()
    w.close()
    w.unlink()


def test_next_in_order_and_overruns(tmp_name):
    w = gb.create(name=tmp_name, schema=gb.ArraySpec("int32", (1,)), capacity=3)
    r = gb.attach(tmp_name)
    for i in range(3):
        w.write(np.array([i], dtype=np.int32))
    seen = [int(r.next(timeout=0.5)[0]) for _ in range(3)]
    assert seen == [0, 1, 2]
    for i in range(10):
        w.write(np.array([100 + i], dtype=np.int32))
    r.next(timeout=0.5)
    assert r.overruns > 0
    r.close()
    w.close()
    w.unlink()


def test_next_timeout_raises_empty(tmp_name):
    w = gb.create(name=tmp_name, schema=gb.ArraySpec("int32", (1,)), capacity=2)
    r = gb.attach(tmp_name)
    with pytest.raises(gb.Empty):
        r.next(timeout=0.05)
    r.close()
    w.close()
    w.unlink()


def test_next_into_reuses_destination(tmp_name):
    w = gb.create(name=tmp_name, schema=gb.ArraySpec("int32", (2,)), capacity=4)
    r = gb.attach(tmp_name)
    w.write(np.array([4, 5], dtype=np.int32))
    out = np.empty(2, dtype=np.int32)
    assert r.next_into(out, timeout=0.5) == 0
    assert out.tolist() == [4, 5]
    r.close()
    w.close()
    w.unlink()


def test_next_batch_into_drains_without_per_sample_allocations(tmp_name):
    w = gb.create(name=tmp_name, schema=gb.ArraySpec("int32", (2,)), capacity=8)
    r = gb.attach(tmp_name)
    for i in range(3):
        w.write(np.array([i, i + 10], dtype=np.int32))
    out = np.empty((2, 2), dtype=np.int32)
    assert r.next_batch_into(out, timeout=0.5) == 2
    assert out.tolist() == [[0, 10], [1, 11]]
    assert r.next_batch_into(out, timeout=0.5) == 1
    assert out[0].tolist() == [2, 12]
    r.close()
    w.close()
    w.unlink()


def test_message_reader_validates(tmp_name):
    class M(pydantic.BaseModel):
        gain: float
        cam_on: bool

    w = gb.create(name=tmp_name, schema=M, capacity=4, max_bytes=256)
    w.write(M(gain=2.5, cam_on=False))
    r = gb.attach(tmp_name, model=M)
    msg = r.latest()
    assert isinstance(msg, M) and msg.gain == 2.5 and msg.cam_on is False
    r.close()
    w.close()
    w.unlink()


def test_schema_mismatch_raises(tmp_name):
    class M(pydantic.BaseModel):
        gain: float

    class N(pydantic.BaseModel):
        different: int

    w = gb.create(name=tmp_name, schema=M, capacity=4, max_bytes=256)
    with pytest.raises(gb.SchemaMismatch):
        gb.attach(tmp_name, model=N)
    w.close()
    w.unlink()


def test_on_data_callback_fires(tmp_name):
    import time
    w = gb.create(name=tmp_name, schema=gb.ArraySpec("int32", (1,)), capacity=8)
    r = gb.attach(tmp_name)
    got = []
    h = r.on_data(lambda sample, seq: got.append(int(sample[0])), mode="next")
    time.sleep(0.05)
    for i in range(3):
        w.write(np.array([i], dtype=np.int32))
    time.sleep(0.3)
    h.stop()
    assert got == [0, 1, 2]
    r.close()
    w.close()
    w.unlink()


def test_writer_alive(tmp_name):
    w = gb.create(name=tmp_name, schema=gb.ArraySpec("int32", (1,)), capacity=4)
    r = gb.attach(tmp_name)
    w.write(np.array([1], dtype=np.int32))
    assert r.writer_alive is True
    r.close()
    w.close()
    w.unlink()


def test_attach_missing_raises(tmp_name):
    with pytest.raises(gb.BufferNotFound):
        gb.attach(tmp_name)
