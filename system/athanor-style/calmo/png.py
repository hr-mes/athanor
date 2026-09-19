"""A deterministic 8-bit RGB PNG writer: no timestamps, fixed compression level."""
import struct
import zlib


def _chunk(kind, data):
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def encode(width, height, rows):
    """`rows` yields `height` byte strings of `width * 3` bytes each."""
    raw = bytearray()
    count = 0
    for row in rows:
        if len(row) != width * 3:
            raise ValueError(f"row {count} has {len(row)} bytes, expected {width * 3}")
        raw += b"\x00" + row
        count += 1
    if count != height:
        raise ValueError(f"{count} rows, expected {height}")
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + _chunk(b"IEND", b""))
