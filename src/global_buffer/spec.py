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


def model_schema_bytes(model):
    """Canonical, stable JSON-schema bytes for a pydantic model."""
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
        }
    raise TypeError(
        "schema must be a gb.ArraySpec or a pydantic.BaseModel subclass, "
        f"got {schema!r}"
    )
