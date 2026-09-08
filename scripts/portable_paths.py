"""Fail-closed path classification for cross-platform ImgGen2 inputs."""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import sys
from urllib.parse import unquote, urlparse


class PathCompatibilityError(ValueError):
    """A path belongs to another OS or is unsafe on the target OS."""


def is_symlink_or_reparse(path: Path) -> bool:
    """Detect POSIX symlinks and Windows junction/reparse points."""
    try:
        if path.is_symlink():
            return True
        info = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return False
    except (OSError, AttributeError, TypeError):
        return True  # Unknown filesystem identity must not be accepted as safe.
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
_WINDOWS_UNC = re.compile(r"^(?:\\\\|//)[^\\/]+[\\/][^\\/]+")
_WSL_MOUNT = re.compile(r"^/mnt/([A-Za-z])(?:/(.*))?$")
_WINDOWS_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$", re.IGNORECASE)
_MAC_ROOTS = ("/Users/", "/Volumes/", "/Applications/", "/System/", "/Library/")
_LINUX_ROOTS = ("/home/", "/var/", "/opt/", "/srv/", "/etc/", "/usr/")


def _platform_name(platform: str | None) -> str:
    return sys.platform if platform is None else platform


def _file_uri_to_path(value: str, platform: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme.lower() != "file":
        return value
    if parsed.username or parsed.password:
        raise PathCompatibilityError("file URI must not contain credentials")
    decoded = unquote(parsed.path)
    if platform.startswith("win"):
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            return f"\\\\{parsed.netloc}{decoded.replace('/', chr(92))}"
        if re.match(r"^/[A-Za-z]:/", decoded):
            decoded = decoded[1:]
        return decoded.replace("/", "\\")
    if parsed.netloc not in {"", "localhost"}:
        raise PathCompatibilityError("remote file URI is not a local path on this host")
    return decoded


def classify_path(value: str) -> str:
    """Classify syntax without touching the filesystem."""
    if not isinstance(value, str) or not value:
        return "invalid"
    if value.lower().startswith("file:"):
        parsed = urlparse(value)
        candidate = unquote(parsed.path)
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            return "windows_unc_uri"
        if re.match(r"^/[A-Za-z]:/", candidate):
            return "windows_file_uri"
        value = candidate
    if _WINDOWS_DRIVE.match(value):
        return "windows_absolute"
    if _WINDOWS_UNC.match(value):
        return "windows_unc"
    if any(value.startswith(root) for root in _MAC_ROOTS):
        return "macos_absolute"
    if _WSL_MOUNT.match(value):
        return "wsl_mount"
    if any(value.startswith(root) for root in _LINUX_ROOTS) or value == "/tmp" or value.startswith("/tmp/"):
        return "linux_absolute"
    if value.startswith("/"):
        return "posix_absolute"
    if "\\" in value:
        return "windows_relative"
    return "portable_relative"


def _validate_windows_components(value: str) -> None:
    path = PureWindowsPath(value)
    for component in path.parts:
        if component in {path.anchor, "\\", "/"}:
            continue
        name = component.rstrip("\\/")
        stem = name.rstrip(" .")
        if name != stem:
            raise PathCompatibilityError("Windows path components must not end with a space or dot")
        if _WINDOWS_RESERVED.fullmatch(stem):
            raise PathCompatibilityError(f"Windows reserved device name is not a file path: {component}")
        if any(char in stem for char in '<>"|?*'):
            raise PathCompatibilityError(f"Windows path contains a reserved character: {component}")


def _windows_long_path(value: str) -> str:
    if len(value) < 240 or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value.lstrip("\\")
    if _WINDOWS_DRIVE.match(value):
        return "\\\\?\\" + value
    return value


def normalize_local_path(
    value: str,
    *,
    platform: str | None = None,
    wsl: bool | None = None,
    field: str = "path",
) -> str:
    """Normalize a path only when the mapping is deterministic; otherwise fail closed."""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise PathCompatibilityError(f"{field} must be a non-empty path without NUL bytes")
    platform = _platform_name(platform)
    wsl = bool(os.environ.get("WSL_INTEROP") or os.environ.get("WSL_DISTRO_NAME")) if wsl is None else wsl
    value = _file_uri_to_path(value, platform)
    kind = classify_path(value)

    if platform.startswith("win"):
        if kind == "macos_absolute":
            raise PathCompatibilityError(
                f"{field} is a macOS path and cannot be guessed on Windows; transfer or attach the file, "
                "or provide its real Windows/UNC path"
            )
        if kind in {"linux_absolute", "posix_absolute"}:
            raise PathCompatibilityError(
                f"{field} is a POSIX path and is not a Windows filesystem path; transfer the file or provide "
                "a real Windows/UNC path"
            )
        if kind == "wsl_mount":
            match = _WSL_MOUNT.match(value)
            assert match is not None
            rest = (match.group(2) or "").replace("/", "\\")
            value = f"{match.group(1).upper()}:\\{rest}".rstrip("\\")
        elif kind in {"windows_unc", "windows_unc_uri"}:
            value = str(PureWindowsPath(value))
        elif kind == "portable_relative":
            value = value.replace("/", "\\")
        _validate_windows_components(value)
        return _windows_long_path(value)

    if kind in {"windows_absolute", "windows_unc", "windows_relative", "windows_file_uri", "windows_unc_uri"}:
        if platform.startswith("linux") and wsl and kind == "windows_absolute":
            path = PureWindowsPath(value)
            drive = path.drive.rstrip(":").lower()
            rest = "/".join(path.parts[1:])
            return f"/mnt/{drive}/{rest}" if rest else f"/mnt/{drive}"
        raise PathCompatibilityError(
            f"{field} is a Windows path and cannot be guessed on this host; transfer or attach the file, "
            "or provide its real local path"
        )
    return value


def foreign_path_message(value: str, *, platform: str | None = None, field: str = "path") -> str | None:
    """Return an actionable cross-OS error, or None when syntax is local/portable."""
    try:
        normalize_local_path(value, platform=platform, field=field)
    except PathCompatibilityError as exc:
        return str(exc)
    return None
