"""Extra coverage: introspection, lifecycle, edge cases, raw messages."""
import threading
import time

import numpy as np
import pydantic
import pytest

import global_buffer as gb


# ---- introspection properties ----
def test_reader_array_introspection(make_writer, tmp_name):
    make_writer(gb.ArraySpec("complex64", (64, 4)), capacity=4)
    r = gb.attach(tmp_name)
    assert tuple(r.shape) == (64, 4)
    assert r.dtype == np.dtype("complex64")
    assert r.nbytes == 64 * 4 * 8
    r.close()


def test_reader_message_introspection_is_none(make_writer, tmp_name):
    class M(pydantic.BaseModel):
        x: int

    make_writer(M, capacity=2, max_bytes=128)
    r = gb.attach(tmp_name, model=M)
    assert r.shape is None and r.dtype is None and r.nbytes is None
    r.close()


# ---- lifecycle / errors ----
def test_capacity_must_be_positive(tmp_name):
    with pytest.raises(ValueError):
        gb.create(name=tmp_name, schema=gb.ArraySpec("uint8", (1,)), capacity=0)


def test_reserve_on_message_buffer_raises(make_writer, tmp_name):
    class M(pydantic.BaseModel):
        x: int

    w = make_writer(M, capacity=2, max_bytes=128)
    with pytest.raises(TypeError):
        with w.reserve():
            pass


def test_write_after_close_raises(make_writer, tmp_name):
    w = make_writer(gb.ArraySpec("uint8", (1,)), capacity=2)
    w.write(np.array([1], dtype=np.uint8))
    w.close()
    with pytest.raises(gb.BufferClosed):
        w.write(np.array([2], dtype=np.uint8))


def test_read_after_close_raises(make_writer, tmp_name):
    make_writer(gb.ArraySpec("uint8", (1,)), capacity=2)
    r = gb.attach(tmp_name)
    r.close()
    with pytest.raises(gb.BufferClosed):
        r.latest()


def test_close_is_idempotent(make_writer, tmp_name):
    w = make_writer(gb.ArraySpec("uint8", (1,)), capacity=2)
    w.close()
    w.close()  # no raise


def test_unlink_is_idempotent(tmp_name):
    w = gb.create(name=tmp_name, schema=gb.ArraySpec("uint8", (1,)), capacity=2)
    w.close()
    w.unlink()
    w.unlink()  # no raise


def test_context_manager_closes(tmp_name):
    with gb.create(name=tmp_name, schema=gb.ArraySpec("uint8", (1,)),
                   capacity=2) as w:
        w.write(np.array([5], dtype=np.uint8))
    assert w._closed is True
    gb.unlink(tmp_name)


# ---- messages ----
def test_message_write_accepts_dict(make_writer, tmp_name):
    class M(pydantic.BaseModel):
        gain: float
        cam_on: bool

    w = make_writer(M, capacity=4, max_bytes=256)
    w.write({"gain": 9.0, "cam_on": True})  # dict, validated on encode
    r = gb.attach(tmp_name, model=M)
    msg = r.latest()
    assert msg.gain == 9.0 and msg.cam_on is True
    r.close()


def test_message_reader_without_model_returns_dict(make_writer, tmp_name):
    class M(pydantic.BaseModel):
        gain: float

    w = make_writer(M, capacity=4, max_bytes=256)
    w.write(M(gain=1.25))
    r = gb.attach(tmp_name)  # no model -> raw mode
    out = r.latest()
    assert out == {"gain": 1.25}
    r.close()


# ---- multi-reader + callbacks ----
def test_multiple_readers_see_same_data(make_writer, tmp_name):
    w = make_writer(gb.ArraySpec("int32", (2,)), capacity=4)
    w.write(np.array([7, 8], dtype=np.int32))
    r1, r2 = gb.attach(tmp_name), gb.attach(tmp_name)
    assert np.array_equal(r1.latest(), r2.latest())
    assert np.array_equal(r1.latest(), np.array([7, 8], dtype=np.int32))
    r1.close()
    r2.close()


def test_on_data_latest_mode_gets_newest(make_writer, tmp_name):
    w = make_writer(gb.ArraySpec("int32", (1,)), capacity=8)
    r = gb.attach(tmp_name)
    seen = []
    h = r.on_data(lambda s, seq: seen.append(int(s[0])), mode="latest")
    time.sleep(0.05)
    for i in range(5):
        w.write(np.array([i], dtype=np.int32))
        time.sleep(0.02)
    time.sleep(0.1)
    h.stop()
    assert seen and seen[-1] == 4  # latest coalesces to the newest
    r.close()


def test_consumer_dropped_aliases_overruns(make_writer, tmp_name):
    class C(gb.Consumer):
        def callback(self):
            time.sleep(0.005)  # slow consumer -> falls behind

    w = make_writer(gb.ArraySpec("int32", (1,)), capacity=3)
    ob = C.attach(tmp_name, mode="next")
    ob.start()
    time.sleep(0.05)
    for i in range(50):
        w.write(np.array([i], dtype=np.int32))
    time.sleep(0.3)
    ob.stop()
    assert ob.dropped == ob.overruns
    assert ob.dropped > 0  # it fell behind on purpose


def test_on_data_invalid_mode_raises(make_writer, tmp_name):
    make_writer(gb.ArraySpec("int32", (1,)), capacity=2)
    r = gb.attach(tmp_name)
    with pytest.raises(ValueError):
        r.on_data(lambda s, seq: None, mode="bogus")
    r.close()


def test_next_blocks_until_data_arrives(make_writer, tmp_name):
    w = make_writer(gb.ArraySpec("int32", (1,)), capacity=4)
    r = gb.attach(tmp_name)
    result = {}

    def consume():
        result["v"] = int(r.next(timeout=3.0)[0])

    t = threading.Thread(target=consume)
    t.start()
    time.sleep(0.1)
    w.write(np.array([99], dtype=np.int32))
    t.join(3.0)
    assert result["v"] == 99
    r.close()


def test_poll_tuning_still_delivers(make_writer, tmp_name):
    # a high poll cap must not break delivery, only relax wake latency
    w = make_writer(gb.ArraySpec("int32", (1,)), capacity=4)
    r = gb.attach(tmp_name, poll_max=0.05, poll_min=0.001)
    assert r._poll_max == 0.05 and r._poll_min == 0.001
    seen = []
    h = r.on_data(lambda s, seq: seen.append(int(s[0])), mode="next")
    time.sleep(0.05)
    for i in range(3):
        w.write(np.array([i], dtype=np.int32))
    time.sleep(0.5)
    h.stop()
    assert seen == [0, 1, 2]
    r.close()


def test_poll_tuning_via_consumer(make_writer, tmp_name):
    w = make_writer(gb.ArraySpec("int32", (1,)), capacity=4)

    class C(gb.Consumer):
        def callback(self):
            pass

    ob = C.attach(tmp_name, mode="latest", poll_max=0.03)
    assert ob._poll_max == 0.03
    ob.start()
    time.sleep(0.05)
    w.write(np.array([5], dtype=np.int32))
    time.sleep(0.2)
    ob.stop()
    assert ob.seq == 0
