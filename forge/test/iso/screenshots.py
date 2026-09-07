#!/usr/bin/env python3
"""Converts the run's QEMU screendumps to PNG, so a person can open them.

Usage: screenshots.py DIR

QEMU writes screendumps as binary PPM, three megabytes each and openable by almost
nothing. This rewrites every screen-*.ppm in DIR as a PNG beside it and removes the PPM,
using only the standard library: an artifact people are meant to look at should not need
a toolchain to look at, and the job should not install one to produce it.
"""

import pathlib
import struct
import sys
import zlib


def read_ppm(path: pathlib.Path) -> tuple[int, int, bytes]:
    with path.open("rb") as f:
        if f.readline().strip() != b"P6":
            raise ValueError(f"{path}: not a binary PPM")
        line = f.readline()
        while line.startswith(b"#"):
            line = f.readline()
        width, height = (int(v) for v in line.split())
        f.readline()  # the maximum value, always 255 from QEMU
        return width, height, f.read()


def chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def to_png(width: int, height: int, pixels: bytes) -> bytes:
    stride = width * 3
    # PNG wants a filter byte in front of every scanline; zero means "store as is".
    raw = b"".join(
        b"\x00" + pixels[y * stride : (y + 1) * stride] for y in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def main() -> int:
    directory = pathlib.Path(sys.argv[1])
    converted = 0
    for ppm in sorted(directory.glob("screen-*.ppm")):
        width, height, pixels = read_ppm(ppm)
        ppm.with_suffix(".png").write_bytes(to_png(width, height, pixels))
        ppm.unlink()
        converted += 1
    print(f"{converted} screenshots converted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
