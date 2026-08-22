import json
from dataclasses import dataclass

import numpy as np

from . import layout


@dataclass(frozen=True)
class ArraySpec:
    dtype: str
    shape: tuple

    def __post_init__(self):
        np.dtype(self.dtype)  # validate eagerly
        object.__setattr__(self, "shape", tuple(int(d) for d in self.shape))

    @property
    def np_dtype(self):
        return np.dtype(self.dtype)

    @property
    def itemsize(self):
        return self.np_dtype.itemsize

    @property
    def nbytes(self):
        n = self.itemsize
        for d in self.shape:
            n *= d
        return n


def _is_pydantic_model(obj):
    try:
        import pydantic
    except ImportError:
        return False
    return isinstance(obj, type) and issubclass(obj, pydantic.BaseModel)


def _is_protobuf_model(obj):
    """Return whether *obj* is a generated protobuf message class."""
    try:
        from google.protobuf.message import Message
    except ImportError:
        return False
    return isinstance(obj, type) and issubclass(obj, Message)


def model_schema_bytes(model):
    """Canonical identity bytes for a Pydantic or protobuf schema."""
    if _is_protobuf_model(model):
        descriptor = model.DESCRIPTOR
        return (descriptor.file.serialized_pb + b"\0" +
                descriptor.full_name.encode("utf-8"))
    return json.dumps(model.model_json_schema(), sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def normalize_schema(schema):
    """Return (kind, info) for either an ArraySpec or a pydantic model class."""
    if isinstance(schema, ArraySpec):
        return layout.KIND_ARRAY, {
            "dtype": schema.np_dtype.name,
            "shape": schema.shape,
            "min_slot_size": schema.nbytes,
            "spec": schema,
        }
    if _is_pydantic_model(schema):
        raw = model_schema_bytes(schema)
        return layout.KIND_MSG, {
            "schema_json": raw,
            "schema_hash": layout.schema_hash(raw),
            "model": schema,
            "codec": layout.MSG_CODEC_MSGPACK,
        }
    if _is_protobuf_model(schema):
        raw = model_schema_bytes(schema)
        return layout.KIND_MSG, {
            "schema_json": raw,
            "schema_hash": layout.schema_hash(raw),
            "model": schema,
            "codec": layout.MSG_CODEC_PROTOBUF,
        }
    raise TypeError(
        "schema must be a gb.ArraySpec, pydantic model, or protobuf message "
        "class, "
        f"got {schema!r}"
    )
