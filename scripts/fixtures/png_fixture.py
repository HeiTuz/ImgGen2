"""Small valid PNGs for offline tests; no image generation provider is called."""
import struct
import zlib


def png_bytes(width=2, height=2, seed=0):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = (b"\0" + bytes((seed % 256, 80, 160)) * width) * height
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
