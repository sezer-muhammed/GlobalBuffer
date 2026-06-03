"""GlobalBuffer: cross-platform, cross-process shared-memory ring buffer.

Zero-copy numpy array streams and pydantic message streams, last-value or
in-order reads, and background callbacks. See the README for the full API.
"""
from ._version import __version__
from .buffer import GlobalBuffer, shm_name
from .consumer import Consumer
from .exceptions import (BufferClosed, BufferExists, BufferNotFound, Empty,
                         GlobalBufferError, SchemaMismatch, TooManyReaders)
from .reader import Reader
from .spec import ArraySpec


def create(name, schema, capacity, max_bytes=None):
    """Create and own a named buffer (writer). ``schema`` is an
    :class:`ArraySpec` or a ``pydantic.BaseModel`` subclass."""
    return GlobalBuffer(name, schema, capacity, max_bytes=max_bytes)


def attach(name, model=None):
    """Attach to an existing named buffer (reader). For message buffers, pass
    ``model=`` to get validated instances and a schema-compatibility check."""
    return Reader(name, model=model)


def unlink(name):
    """Remove a named segment by name (e.g. to clean up after a crash)."""
    from multiprocessing import shared_memory
    try:
        shm = shared_memory.SharedMemory(name=shm_name(name))
    except FileNotFoundError:
        return
    shm.close()
    shm.unlink()


__all__ = [
    "__version__", "ArraySpec", "GlobalBuffer", "Reader", "Consumer",
    "create", "attach", "unlink",
    "GlobalBufferError", "Empty", "SchemaMismatch", "BufferClosed",
    "BufferExists", "BufferNotFound", "TooManyReaders",
]
