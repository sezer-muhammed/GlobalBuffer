import pydantic
from global_buffer.codec import MessageCodec


class M(pydantic.BaseModel):
    gain: float
    cam_on: bool
    name: str = "x"


def test_roundtrip_validated():
    c = MessageCodec(M, validate=True)
    blob = c.encode(M(gain=1.5, cam_on=True, name="pod1"))
    out = c.decode(blob)
    assert isinstance(out, M) and out.gain == 1.5 and out.cam_on is True


def test_encode_accepts_dict():
    c = MessageCodec(M, validate=True)
    blob = c.encode({"gain": 2.0, "cam_on": False})
    out = c.decode(blob)
    assert out.gain == 2.0 and out.name == "x"


def test_raw_mode_returns_dict():
    c = MessageCodec(None, validate=False)
    blob = c.encode({"a": 1, "b": [1, 2, 3]})
    assert c.decode(blob) == {"a": 1, "b": [1, 2, 3]}
