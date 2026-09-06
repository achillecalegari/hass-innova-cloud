"""Minimal protobuf wire-format codec.

The Innova cloud speaks plain protobuf over gRPC. The messages are small, so instead of
depending on the ``protobuf`` package (whose version is pinned by Home Assistant core) we
encode and decode the wire format by hand. Only what the integration needs is implemented:
varint, 32-bit float and length-delimited fields, plus packed repeated varints.
"""

from __future__ import annotations

import struct
from typing import Iterator

WIRE_VARINT = 0
WIRE_FIXED64 = 1
WIRE_LEN = 2
WIRE_FIXED32 = 5


def encode_varint(value: int) -> bytes:
    if value < 0:
        value &= (1 << 64) - 1
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return encode_varint((field << 3) | wire)


class Writer:
    """Accumulates encoded fields of one message."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def varint(self, field: int, value: int | bool | None) -> "Writer":
        if value is None:
            return self
        self._buf += _tag(field, WIRE_VARINT) + encode_varint(int(value))
        return self

    def bool(self, field: int, value: bool | None) -> "Writer":
        return self.varint(field, None if value is None else (1 if value else 0))

    def float32(self, field: int, value: float | None) -> "Writer":
        if value is None:
            return self
        self._buf += _tag(field, WIRE_FIXED32) + struct.pack("<f", float(value))
        return self

    def bytes(self, field: int, value: bytes | None) -> "Writer":
        if value is None:
            return self
        self._buf += _tag(field, WIRE_LEN) + encode_varint(len(value)) + value
        return self

    def string(self, field: int, value: str | None) -> "Writer":
        return self.bytes(field, None if value is None else value.encode("utf-8"))

    def message(self, field: int, value: "Writer | bytes | None") -> "Writer":
        if value is None:
            return self
        return self.bytes(field, value.finish() if isinstance(value, Writer) else value)

    def finish(self) -> bytes:
        return bytes(self._buf)


def decode_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise ValueError("truncated varint")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 70:
            raise ValueError("varint too long")


def iter_fields(buf: bytes) -> Iterator[tuple[int, int, int | bytes]]:
    """Yield (field_number, wire_type, raw_value) for every field in ``buf``.

    Varints are yielded as ``int``; fixed32/fixed64/length-delimited as ``bytes``.
    """
    pos = 0
    end = len(buf)
    while pos < end:
        key, pos = decode_varint(buf, pos)
        field, wire = key >> 3, key & 0x7
        if wire == WIRE_VARINT:
            value, pos = decode_varint(buf, pos)
            yield field, wire, value
        elif wire == WIRE_FIXED64:
            if pos + 8 > end:
                raise ValueError("truncated fixed64")
            yield field, wire, buf[pos : pos + 8]
            pos += 8
        elif wire == WIRE_LEN:
            length, pos = decode_varint(buf, pos)
            if pos + length > end:
                raise ValueError("truncated length-delimited field")
            yield field, wire, buf[pos : pos + length]
            pos += length
        elif wire == WIRE_FIXED32:
            if pos + 4 > end:
                raise ValueError("truncated fixed32")
            yield field, wire, buf[pos : pos + 4]
            pos += 4
        elif wire in (3, 4):  # groups: unsupported but skip gracefully
            raise ValueError("protobuf groups are not supported")
        else:
            raise ValueError(f"unknown wire type {wire}")


class Message:
    """A decoded message: field number -> list of raw values (in wire order)."""

    __slots__ = ("fields", "wires", "raw")

    def __init__(self, buf: bytes) -> None:
        self.raw = buf
        self.fields: dict[int, list[int | bytes]] = {}
        self.wires: dict[int, int] = {}
        for field, wire, value in iter_fields(buf):
            self.fields.setdefault(field, []).append(value)
            self.wires[field] = wire

    def has(self, field: int) -> bool:
        return field in self.fields

    def _last(self, field: int):
        values = self.fields.get(field)
        return values[-1] if values else None

    def int(self, field: int, default: int | None = None) -> int | None:
        value = self._last(field)
        if value is None:
            return default
        if isinstance(value, int):
            return value
        if len(value) == 4:
            return struct.unpack("<i", value)[0]
        if len(value) == 8:
            return struct.unpack("<q", value)[0]
        return default

    def sint32(self, field: int, default: int | None = None) -> int | None:
        """int32 fields are encoded as 64-bit two's complement varints."""
        value = self.int(field)
        if value is None:
            return default
        if value >= 1 << 63:
            value -= 1 << 64
        if value >= 1 << 31:
            value -= 1 << 32
        return value

    def bool(self, field: int, default: bool | None = None) -> bool | None:
        value = self.int(field)
        return default if value is None else bool(value)

    def float(self, field: int, default: float | None = None) -> float | None:
        value = self._last(field)
        if value is None or isinstance(value, int):
            return default
        if len(value) == 4:
            return struct.unpack("<f", value)[0]
        if len(value) == 8:
            return struct.unpack("<d", value)[0]
        return default

    def bytes(self, field: int, default: bytes | None = None) -> bytes | None:
        value = self._last(field)
        return value if isinstance(value, bytes) else default

    def string(self, field: int, default: str | None = None) -> str | None:
        value = self.bytes(field)
        if value is None:
            return default
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return default

    def message(self, field: int) -> "Message | None":
        value = self.bytes(field)
        if value is None:
            return None
        try:
            return Message(value)
        except ValueError:
            return None

    def messages(self, field: int) -> list["Message"]:
        out = []
        for value in self.fields.get(field, []):
            if isinstance(value, bytes):
                try:
                    out.append(Message(value))
                except ValueError:
                    continue
        return out

    def varints(self, field: int) -> list[int]:
        """Repeated varint field, packed (LEN) or unpacked."""
        out: list[int] = []
        for value in self.fields.get(field, []):
            if isinstance(value, int):
                out.append(value)
            else:
                pos = 0
                while pos < len(value):
                    item, pos = decode_varint(value, pos)
                    out.append(item)
        return out

    def to_debug(self) -> dict:
        """Best-effort generic rendering, handy for logging unknown payloads."""
        out: dict = {}
        for field, values in self.fields.items():
            rendered = []
            for value in values:
                if isinstance(value, int):
                    rendered.append(value)
                elif len(value) == 4 and self.wires[field] == WIRE_FIXED32:
                    rendered.append(struct.unpack("<f", value)[0])
                else:
                    try:
                        rendered.append(Message(value).to_debug() if value else {})
                    except ValueError:
                        try:
                            rendered.append(value.decode("utf-8"))
                        except UnicodeDecodeError:
                            rendered.append(value.hex())
            out[field] = rendered if len(rendered) > 1 else rendered[0]
        return out
