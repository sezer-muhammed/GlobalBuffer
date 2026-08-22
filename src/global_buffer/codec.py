import msgspec


def _is_protobuf_model(model):
    try:
        from google.protobuf.message import Message
    except ImportError:
        return False
    return isinstance(model, type) and issubclass(model, Message)


class MessageCodec:
    """Encode/decode msgpack or protobuf messages.

    Pydantic models use msgpack and validated model construction. Protobuf
    models go directly through the generated binary serializer/parser. Without
    a model, raw msgpack decodes to Python objects and raw protobuf returns the
    serialized bytes.
    """

    def __init__(self, model=None, validate=True, codec=None):
        self.model = model
        self.validate = validate and model is not None
        if codec is None:
            self.codec = "protobuf" if _is_protobuf_model(model) else "msgpack"
        elif codec in ("protobuf", 2):
            self.codec = "protobuf"
        elif codec in ("msgpack", 1):
            self.codec = "msgpack"
        else:
            raise ValueError(f"unsupported message codec {codec!r}")
        self._encoder = (msgspec.msgpack.Encoder()
                         if self.codec == "msgpack" else None)
        self._decoder = (msgspec.msgpack.Decoder()
                         if self.codec == "msgpack" else None)

    def encode(self, obj) -> bytes:
        if self.codec == "protobuf":
            if self.model is None:
                if not isinstance(obj, (bytes, bytearray, memoryview)):
                    raise TypeError("raw protobuf mode expects serialized bytes")
                return bytes(obj)
            if isinstance(obj, self.model):
                return obj.SerializeToString()
            if isinstance(obj, dict):
                return self.model(**obj).SerializeToString()
            raise TypeError(
                f"expected {self.model.__name__} or dict, got "
                f"{type(obj).__name__}"
            )
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
        if self.codec == "protobuf":
            if self.model is None:
                return blob
            out = self.model()
            out.ParseFromString(blob)
            return out
        data = self._decoder.decode(blob)
        if self.validate:
            return self.model(**data)
        return data
