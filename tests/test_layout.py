from global_buffer import layout


def test_constants():
    assert layout.MAGIC == 0x46554247
    assert layout.VERSION == 1
    assert layout.KIND_ARRAY == 1 and layout.KIND_MSG == 2
    assert layout.HEADER_SIZE == 4096
    assert layout.NDIM_MAX == 8 and layout.MAX_READERS == 64


def test_align_up():
    assert layout.align_up(1, 64) == 64
    assert layout.align_up(64, 64) == 64
    assert layout.align_up(65, 64) == 128


def test_slot_stride():
    assert layout.slot_stride(100) == 192  # 64 + 100 = 164 -> align64 -> 192


def test_geometry_array():
    g = layout.geometry(layout.KIND_ARRAY, n_slots=9, slot_size=512)
    assert g["registry_off"] == 4096
    assert g["slots_off"] == 4096 + 64 * 64
    assert g["total_size"] == g["slots_off"] + 9 * layout.slot_stride(512)


def test_header_roundtrip_array():
    buf = bytearray(layout.HEADER_SIZE)
    layout.write_array_header(buf, n_slots=9, slot_size=512,
                              dtype="complex64", shape=(64, 4))
    h = layout.read_header(buf)
    assert h["magic"] == layout.MAGIC and h["kind"] == layout.KIND_ARRAY
    assert h["n_slots"] == 9 and h["slot_size"] == 512
    assert h["dtype"] == "complex64" and h["shape"] == (64, 4)


def test_header_roundtrip_msg():
    buf = bytearray(layout.HEADER_SIZE)
    schema = b'{"fields":["gain","cam_on"]}'
    layout.write_msg_header(buf, n_slots=5, slot_size=512,
                            schema_json=schema, schema_hash=0xABCD)
    h = layout.read_header(buf)
    assert h["kind"] == layout.KIND_MSG
    assert h["schema_hash"] == 0xABCD
    assert h["schema_json"] == schema


def test_schema_hash_stable():
    a = layout.schema_hash(b"hello")
    b = layout.schema_hash(b"hello")
    c = layout.schema_hash(b"world")
    assert a == b and a != c and 0 <= a < 2 ** 64
