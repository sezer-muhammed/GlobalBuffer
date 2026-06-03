from .reader import Reader


class Consumer(Reader):
    """Subclassable reader: override :meth:`callback`. The framework sets
    ``self.data`` (decoded sample) and ``self.seq`` before each call, on a
    background thread started by :meth:`start`."""

    def __init__(self, name, model=None, mode="latest"):
        super().__init__(name, model=model)
        self._mode = mode
        self._handle = None
        self.data = None
        self.seq = None

    @classmethod
    def attach(cls, name, model=None, mode="latest"):
        return cls(name, model=model, mode=mode)

    @property
    def dropped(self):
        """Samples skipped because the consumer fell behind (alias of overruns)."""
        return self.overruns

    def callback(self):
        raise NotImplementedError("subclasses must implement callback(self)")

    def _dispatch(self, sample, seq):
        self.data = sample
        self.seq = seq
        self.callback()

    def start(self):
        if self._handle is not None:
            return
        self._handle = super().on_data(self._dispatch, mode=self._mode)

    def stop(self):
        if self._handle is not None:
            self._handle.stop()
            self._handle = None
        self.close()
