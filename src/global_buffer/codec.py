import msgspec


class MessageCodec:
    """Encode/decode messages over msgpack. With a pydantic model, encode accepts
    model instances or dicts and decode returns validated model instances. Without
    a model (raw mode), decode returns plain Python objects."""

    def __init__(self, model=None, validate=True):
        self.model = model
        self.validate = validate and model is not None
        self._encoder = msgspec.msgpack.Encoder()
        self._decoder = msgspec.msgpack.Decoder()

    def encode(self, obj) -> bytes:
        if self.model is not None:
            if isinstance(obj, self.model):
                data = obj.model_dump()
            elif isinstance(obj, dict):
                data = self.model(**obj).model_dump() if self.validate else obj
            else:
                raise TypeError(
                    f"expected {self.model.__name__} or dict, got {type(obj).__name__}"
                )
            return self._encoder.encode(data)
        return self._encoder.encode(obj)

    def decode(self, blob):
        data = self._decoder.decode(blob)
        if self.validate:
            return self.model(**data)
        return data
