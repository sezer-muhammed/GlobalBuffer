"""GlobalBuffer: cross-platform, cross-process shared-memory ring buffer.

Zero-copy numpy array streams and pydantic message streams, last-value or
in-order reads, and background callbacks. See the README for the full API.
"""
from ._version import __version__
from .buffer import GlobalBuffer, open_shm, shm_name
from .consumer import Consumer
from .exceptions import (BufferClosed, BufferExists, BufferNotFound, Empty,
                         GlobalBufferError, SchemaMismatch)
from .reader import Reader
from .spec import ArraySpec


def create(name, schema, capacity, max_bytes=None, heartbeat_interval=0.1):
    """Create and own a named buffer (writer). ``schema`` is an
    :class:`ArraySpec` or a ``pydantic.BaseModel`` subclass. ``heartbeat_interval``
    controls automatic writer liveness stamps; zero restores a stamp on every
    write."""
    return GlobalBuffer(name, schema, capacity, max_bytes=max_bytes,
                        heartbeat_interval=heartbeat_interval)


def attach(name, model=None, poll_min=None, poll_max=None):
    """Attach to an existing named buffer (reader). For message buffers, pass
    ``model=`` to get validated instances and a schema-compatibility check.

    ``poll_max`` raises the wakeup poll-backoff cap (seconds); a larger value
    lowers idle CPU when running many readers, at the cost of up to that much
    extra wake latency (default ~2 ms). ``poll_min`` sets the busy floor."""
    return Reader(name, model=model, poll_min=poll_min, poll_max=poll_max)


def unlink(name):
    """Remove a named segment by name (e.g. to clean up after a crash)."""
    try:
        shm = open_shm(shm_name(name))
    except FileNotFoundError:
        return
    shm.close()
    shm.unlink()


__all__ = [
    "__version__", "ArraySpec", "GlobalBuffer", "Reader", "Consumer",
    "create", "attach", "unlink",
    "GlobalBufferError", "Empty", "SchemaMismatch", "BufferClosed",
    "BufferExists", "BufferNotFound",
]
