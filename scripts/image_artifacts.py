"""Network-free PNG container and byte-identity checks shared by executors."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import stat
import struct
import zlib
from portable_paths import is_symlink_or_reparse


class ArtifactError(ValueError):
    pass


def inspect_png(path: Path) -> dict[str, object]:
    """Validate PNG chunks/CRC and stable bytes without decoding pixels."""
    digest = hashlib.sha256()
    size = 0
    try:
        if is_symlink_or_reparse(path):
            raise ArtifactError("PNG artifact must not be a symlink or reparse point")
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ArtifactError("PNG artifact must be a regular file")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ArtifactError("PNG artifact must be a regular file")

            def read(count):
                nonlocal size
                data = stream.read(count)
                if len(data) != count:
                    raise ArtifactError("Truncated PNG artifact")
                digest.update(data)
                size += len(data)
                return data

            if read(8) != b"\x89PNG\r\n\x1a\n":
                raise ArtifactError("Artifact does not have a PNG signature")
            width = height = image_bytes = 0
            first = True
            while True:
                length, kind = struct.unpack(">I4s", read(8))
                if length > 0x7fffffff or not all(65 <= c <= 90 or 97 <= c <= 122 for c in kind):
                    raise ArtifactError("Invalid PNG chunk")
                if first and (kind != b"IHDR" or length != 13):
                    raise ArtifactError("PNG must start with a 13-byte IHDR")
                if not first and kind == b"IHDR":
                    raise ArtifactError("Duplicate PNG IHDR")
                crc = zlib.crc32(kind)
                remaining = length
                header = b""
                while remaining:
                    data = read(min(remaining, 1024 * 1024))
                    crc = zlib.crc32(data, crc)
                    if first:
                        header += data
                    remaining -= len(data)
                if struct.unpack(">I", read(4))[0] != crc & 0xffffffff:
                    raise ArtifactError("PNG chunk checksum mismatch")
                if first:
                    width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", header)
                    depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
                    if not 0 < width <= 0x7fffffff or not 0 < height <= 0x7fffffff or depth not in depths.get(color, set()) or compression or filtering or interlace not in {0, 1}:
                        raise ArtifactError("Invalid PNG dimensions or encoding")
                    first = False
                if kind == b"IDAT":
                    image_bytes += length
                if kind == b"IEND":
                    if length or not image_bytes or stream.read(1):
                        raise ArtifactError("Invalid PNG end or missing image data")
                    break
            after = os.fstat(stream.fileno())
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            if any(getattr(before, f) != getattr(after, f) for f in fields) or size != before.st_size:
                raise ArtifactError("PNG artifact changed during inspection")
    except OSError as exc:
        raise ArtifactError("PNG artifact is missing, unsafe, or unreadable") from exc
    return {"format": "png", "width": width, "height": height, "sha256": digest.hexdigest(), "size": size}
