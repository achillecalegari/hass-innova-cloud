"""Round-trip tests for the hand-written protobuf codec."""

from api.protobuf import Message, Writer, encode_varint


def test_varint():
    assert encode_varint(0) == b"\x00"
    assert encode_varint(1) == b"\x01"
    assert encode_varint(300) == b"\xac\x02"
    assert encode_varint(-1) == b"\xff" * 9 + b"\x01"


def test_writer_and_reader_roundtrip():
    inner = Writer().float32(1, 21.5).varint(2, 7)
    buf = Writer().bool(1, True).varint(2, 300).bytes(3, b"\x01\x02").string(4, "ciao").message(5, inner).finish()
    msg = Message(buf)
    assert msg.bool(1) is True
    assert msg.int(2) == 300
    assert msg.bytes(3) == b"\x01\x02"
    assert msg.string(4) == "ciao"
    sub = msg.message(5)
    assert abs(sub.float(1) - 21.5) < 1e-6
    assert sub.int(2) == 7
    assert msg.has(6) is False
    assert msg.int(6, 9) == 9


def test_packed_and_unpacked_repeated():
    packed = Writer().bytes(3, encode_varint(1) + encode_varint(3) + encode_varint(5)).finish()
    assert Message(packed).varints(3) == [1, 3, 5]
    unpacked = Writer().varint(3, 1).varint(3, 3).finish()
    assert Message(unpacked).varints(3) == [1, 3]


def test_sint32_negative():
    # int32 -55 is stored as a 64-bit two's complement varint
    buf = Writer().varint(2, -55).finish()
    assert Message(buf).sint32(2) == -55


def test_to_debug_renders_floats_and_nested():
    buf = Writer().float32(1, 1.5).message(2, Writer().varint(1, 4)).finish()
    debug = Message(buf).to_debug()
    assert debug[1] == 1.5
    assert debug[2] == {1: 4}
