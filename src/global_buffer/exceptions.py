class GlobalBufferError(Exception):
    """Base class for all GlobalBuffer errors."""


class Empty(GlobalBufferError):
    """No new sample available within the timeout (next mode)."""


class SchemaMismatch(GlobalBufferError):
    """Attached schema/model does not match the segment's declared schema."""


class BufferClosed(GlobalBufferError):
    """Operation attempted on a closed handle."""


class BufferExists(GlobalBufferError):
    """create() called for a name whose segment already exists."""


class BufferNotFound(GlobalBufferError):
    """attach() called for a name with no live segment."""

