import pytest
from global_buffer.spec import ArraySpec, normalize_schema
from global_buffer import layout


def test_arrayspec_nbytes():
    s = ArraySpec(dtype="complex64", shape=(64, 4))
    assert s.itemsize == 8
    assert s.nbytes == 64 * 4 * 8


def test_arrayspec_validates_dtype():
    with pytest.raises(Exception):
        ArraySpec(dtype="not-a-dtype", shape=(2,))


def test_normalize_array():
    s = ArraySpec(dtype="float32", shape=(10,))
    kind, info = normalize_schema(s)
    assert kind == layout.KIND_ARRAY
    assert info["dtype"] == "float32" and info["shape"] == (10,)
    assert info["min_slot_size"] == 40


def test_normalize_message_pydantic():
    import pydantic

    class M(pydantic.BaseModel):
        a: int
        b: float

    kind, info = normalize_schema(M)
    assert kind == layout.KIND_MSG
    assert isinstance(info["schema_json"], (bytes, bytearray))
    assert info["schema_hash"] == layout.schema_hash(info["schema_json"])


def test_normalize_rejects_other():
    with pytest.raises(TypeError):
        normalize_schema(123)
