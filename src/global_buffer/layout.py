import hashlib
import struct

MAGIC = 0x46554247          # b"GBUF" little-endian
VERSION = 1
KIND_ARRAY = 1
KIND_MSG = 2
NDIM_MAX = 8
MAX_READERS = 64
HEADER_SIZE = 4096
SLOT_ALIGN = 64
SLOT_PAYLOAD_OFF = 64
REGISTRY_ENTRY_SIZE = 64

# header field offsets
O_MAGIC = 0
O_VERSION = 4
O_KIND = 8
O_NSLOTS = 12
O_SLOT_STRIDE = 16
O_SLOT_SIZE = 24
O_PAYLOAD_OFF = 32
O_MAX_READERS = 36
O_LATEST_COUNT = 40      # atomic u64
O_WRITER_PID = 48
O_WRITER_HB = 56         # atomic u64
O_REGISTRY_OFF = 64
O_SLOTS_OFF = 72
O_SCHEMA_HASH = 80
O_SCHEMA_JSON_LEN = 88
O_DTYPE = 128            # char[16]
O_NDIM = 144
O_SHAPE = 152            # u64[NDIM_MAX]
O_SCHEMA_JSON = 256

# registry entry offsets
R_PID = 0
R_INDEX = 8
R_CURSOR = 16
R_ALIVE = 24             # atomic u32
R_HEARTBEAT = 32         # atomic u64

# slot offsets
S_LOCK = 0               # atomic u32
S_SEQ = 8                # atomic u64
S_LENGTH = 16


def align_up(n, a):
    return (n + a - 1) // a * a


def slot_stride(slot_size):
    return align_up(SLOT_PAYLOAD_OFF + slot_size, SLOT_ALIGN)


def geometry(kind, n_slots, slot_size):
    registry_off = HEADER_SIZE
    slots_off = align_up(registry_off + MAX_READERS * REGISTRY_ENTRY_SIZE, HEADER_SIZE)
    stride = slot_stride(slot_size)
    total = slots_off + n_slots * stride
    return {
        "registry_off": registry_off,
        "slots_off": slots_off,
        "slot_stride": stride,
        "total_size": total,
    }


def schema_hash(data: bytes) -> int:
    return int.from_bytes(hashlib.blake2b(data, digest_size=8).digest(), "little")


def _write_common(buf, kind, n_slots, slot_size):
    g = geometry(kind, n_slots, slot_size)
    struct.pack_into("<I", buf, O_MAGIC, MAGIC)
    struct.pack_into("<I", buf, O_VERSION, VERSION)
    struct.pack_into("<I", buf, O_KIND, kind)
    struct.pack_into("<I", buf, O_NSLOTS, n_slots)
    struct.pack_into("<Q", buf, O_SLOT_STRIDE, g["slot_stride"])
    struct.pack_into("<Q", buf, O_SLOT_SIZE, slot_size)
    struct.pack_into("<I", buf, O_PAYLOAD_OFF, SLOT_PAYLOAD_OFF)
    struct.pack_into("<I", buf, O_MAX_READERS, MAX_READERS)
    struct.pack_into("<Q", buf, O_LATEST_COUNT, 0)
    struct.pack_into("<Q", buf, O_WRITER_HB, 0)
    struct.pack_into("<Q", buf, O_REGISTRY_OFF, g["registry_off"])
    struct.pack_into("<Q", buf, O_SLOTS_OFF, g["slots_off"])
    return g


def write_array_header(buf, n_slots, slot_size, dtype, shape):
    _write_common(buf, KIND_ARRAY, n_slots, slot_size)
    db = dtype.encode("ascii")
    if len(db) > 16:
        raise ValueError(f"dtype name too long: {dtype}")
    struct.pack_into("16s", buf, O_DTYPE, db)
    if len(shape) > NDIM_MAX:
        raise ValueError(f"ndim {len(shape)} exceeds NDIM_MAX {NDIM_MAX}")
    struct.pack_into("<I", buf, O_NDIM, len(shape))
    for i, d in enumerate(shape):
        struct.pack_into("<Q", buf, O_SHAPE + 8 * i, int(d))


def write_msg_header(buf, n_slots, slot_size, schema_json, schema_hash):
    _write_common(buf, KIND_MSG, n_slots, slot_size)
    struct.pack_into("<Q", buf, O_SCHEMA_HASH, schema_hash)
    if len(schema_json) > HEADER_SIZE - O_SCHEMA_JSON:
        raise ValueError("schema_json too large for header")
    struct.pack_into("<I", buf, O_SCHEMA_JSON_LEN, len(schema_json))
    buf[O_SCHEMA_JSON:O_SCHEMA_JSON + len(schema_json)] = schema_json


def write_writer_pid(buf, pid):
    struct.pack_into("<Q", buf, O_WRITER_PID, int(pid))


def read_header(buf):
    (magic, version, kind, n_slots) = struct.unpack_from("<IIII", buf, 0)
    slot_stride_v = struct.unpack_from("<Q", buf, O_SLOT_STRIDE)[0]
    slot_size = struct.unpack_from("<Q", buf, O_SLOT_SIZE)[0]
    payload_off = struct.unpack_from("<I", buf, O_PAYLOAD_OFF)[0]
    max_readers = struct.unpack_from("<I", buf, O_MAX_READERS)[0]
    registry_off = struct.unpack_from("<Q", buf, O_REGISTRY_OFF)[0]
    slots_off = struct.unpack_from("<Q", buf, O_SLOTS_OFF)[0]
    schema_hash_v = struct.unpack_from("<Q", buf, O_SCHEMA_HASH)[0]
    h = {
        "magic": magic, "version": version, "kind": kind, "n_slots": n_slots,
        "slot_stride": slot_stride_v, "slot_size": slot_size,
        "payload_off": payload_off, "max_readers": max_readers,
        "registry_off": registry_off, "slots_off": slots_off,
        "schema_hash": schema_hash_v,
    }
    if kind == KIND_ARRAY:
        dtype = struct.unpack_from("16s", buf, O_DTYPE)[0].rstrip(b"\x00").decode("ascii")
        ndim = struct.unpack_from("<I", buf, O_NDIM)[0]
        shape = tuple(struct.unpack_from("<Q", buf, O_SHAPE + 8 * i)[0] for i in range(ndim))
        h["dtype"] = dtype
        h["shape"] = shape
    elif kind == KIND_MSG:
        n = struct.unpack_from("<I", buf, O_SCHEMA_JSON_LEN)[0]
        h["schema_json"] = bytes(buf[O_SCHEMA_JSON:O_SCHEMA_JSON + n])
    return h
