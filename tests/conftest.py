import itertools
import os

import pytest

import global_buffer as gb

_counter = itertools.count()


@pytest.fixture
def tmp_name():
    return f"gbtest_{os.getpid()}_{next(_counter)}"


@pytest.fixture
def make_writer(tmp_name):
    """Factory that creates GlobalBuffers and guarantees close()+unlink() teardown
    even if the test body raises (no leaked segments across runs)."""
    created = []

    def _make(schema, capacity=4, max_bytes=None, name=None):
        w = gb.create(name=name or tmp_name, schema=schema, capacity=capacity,
                      max_bytes=max_bytes)
        created.append(w)
        return w

    yield _make
    for w in created:
        try:
            w.close()
        finally:
            w.unlink()
