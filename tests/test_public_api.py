import numpy as np
import pytest

import global_buffer as gb


def test_exceptions_hierarchy():
    from global_buffer import exceptions as e
    for name in ["Empty", "SchemaMismatch", "BufferClosed",
                 "BufferExists", "BufferNotFound"]:
        assert issubclass(getattr(e, name), e.GlobalBufferError)


def test_module_exports():
    for n in ["create", "attach", "unlink", "ArraySpec", "GlobalBuffer",
              "Reader", "Consumer", "Empty", "SchemaMismatch"]:
        assert hasattr(gb, n)


def test_unlink_by_name(tmp_name):
    w = gb.create(name=tmp_name, schema=gb.ArraySpec("uint8", (1,)), capacity=2)
    w.write(np.array([1], dtype=np.uint8))
    w.close()
    gb.unlink(tmp_name)
    with pytest.raises(gb.BufferNotFound):
        gb.attach(tmp_name)
