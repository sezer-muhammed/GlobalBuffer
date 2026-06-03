from .reader import Reader


class Consumer(Reader):
    """Subclassable reader: override :meth:`callback`. The framework sets
    ``self.data`` (decoded sample) and ``self.seq`` before each call, on a
    background thread started by :meth:`start`."""

    def __init__(self, name, model=None, mode="latest", zero_copy=False):
        super().__init__(name, model=model)
        self._mode = mode
        self._zero_copy = zero_copy
        self._handle = None
        self.data = None
        self.seq = None
        self.dropped = 0

    @classmethod
    def attach(cls, name, model=None, mode="latest", zero_copy=False):
        return cls(name, model=model, mode=mode, zero_copy=zero_copy)

    def callback(self):
        raise NotImplementedError("subclasses must implement callback(self)")

    def _dispatch(self, sample, seq):
        self.data = sample
        self.seq = seq
        self.callback()

    def start(self):
        if self._handle is not None:
            return
        self._handle = super().on_data(self._dispatch, mode=self._mode,
                                       zero_copy=self._zero_copy)

    def stop(self):
        if self._handle is not None:
            self._handle.stop()
            self._handle = None
        self.close()
