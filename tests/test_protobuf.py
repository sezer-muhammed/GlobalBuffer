import pytest

import global_buffer as gb
from global_buffer.codec import MessageCodec
from global_buffer.spec import normalize_schema
from global_buffer import layout


def make_message_class(file_name="status.proto", field_name="gain"):
    pytest.importorskip("google.protobuf")
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

    fd = descriptor_pb2.FileDescriptorProto(
        name=file_name, package="global_buffer_test"
    )
    msg = fd.message_type.add(name="Status")
    field = msg.field.add(
        name=field_name,
        number=1,
        label=descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
        type=descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT,
    )
    descriptor = descriptor_pool.DescriptorPool().Add(fd)
    return message_factory.GetMessageClass(
        descriptor.message_types_by_name["Status"]
    )


def test_protobuf_codec_roundtrip():
    Status = make_message_class()
    codec = MessageCodec(Status)
    blob = codec.encode(Status(gain=1.25))
    out = codec.decode(blob)
    assert isinstance(out, Status)
    assert out.gain == 1.25


def test_normalize_protobuf_schema():
    Status = make_message_class("normalize.proto")
    kind, info = normalize_schema(Status)
    assert kind == layout.KIND_MSG
    assert info["codec"] == layout.MSG_CODEC_PROTOBUF
    assert info["schema_hash"] == layout.schema_hash(info["schema_json"])


def test_protobuf_buffer_and_raw_attach(tmp_name):
    Status = make_message_class("buffer.proto")
    writer = gb.create(tmp_name, Status, capacity=4, max_bytes=128)
    value = Status(gain=3.5)
    writer.write(value)

    typed = gb.attach(tmp_name, model=Status)
    out = typed.latest()
    assert isinstance(out, Status) and out.gain == 3.5

    raw = gb.attach(tmp_name)
    assert raw.latest() == value.SerializeToString()

    raw.close()
    typed.close()
    writer.close()
    writer.unlink()


def test_protobuf_schema_mismatch(tmp_name):
    Status = make_message_class("mismatch_a.proto", "gain")
    Other = make_message_class("mismatch_b.proto", "value")
    writer = gb.create(tmp_name, Status, capacity=2, max_bytes=128)
    with pytest.raises(gb.SchemaMismatch):
        gb.attach(tmp_name, model=Other)
    writer.close()
    writer.unlink()
