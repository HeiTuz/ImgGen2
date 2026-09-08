"""Network-free PNG/JPEG container and byte-identity checks shared by executors."""
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


def inspect_image(path: Path) -> dict:
    if is_symlink_or_reparse(path) or not path.is_file():
        raise ArtifactError("Artifact must be a regular, non-symlink file")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ArtifactError("Image artifact must be a regular file")
        data = stream.read()
        after = os.fstat(stream.fileno())
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if len(data) != before.st_size or any(getattr(before, k) != getattr(after, k) for k in fields):
            raise ArtifactError("Image changed during inspection")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return inspect_png(path)
    # Check JPEG framing and dimensions; this does not decode pixels or replace QC.
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise ArtifactError("Unsupported or truncated image; expected JPEG or PNG")
    i, dimensions, marker = 2, None, None
    while i < len(data) - 2:
        if data[i] != 255:
            raise ArtifactError("Invalid JPEG marker")
        while i < len(data) and data[i] == 255:
            i += 1
        if i >= len(data):
            break
        marker = data[i]
        i += 1
        if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
            continue
        length = int.from_bytes(data[i:i + 2], "big")
        if length < 2 or i + length > len(data):
            raise ArtifactError("Truncated JPEG segment")
        if marker == 0xDA:
            if length < 6 or i + length >= len(data) - 2:
                raise ArtifactError("JPEG has a truncated or empty scan")
            break
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if length < 8:
                raise ArtifactError("Invalid JPEG frame")
            dimensions = (int.from_bytes(data[i + 5:i + 7], "big"), int.from_bytes(data[i + 3:i + 5], "big"))
        i += length
    if not dimensions or min(dimensions) < 1 or marker != 0xDA:
        raise ArtifactError("JPEG has no valid frame and scan")
    return {"format": "jpeg", "width": dimensions[0], "height": dimensions[1],
            "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
