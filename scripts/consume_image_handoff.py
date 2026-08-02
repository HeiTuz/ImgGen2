#!/usr/bin/env python3
"""Validate and consume the portable HeiTuz image-production handoff."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Sequence
from urllib.parse import urlparse

import codex_subscription_transport as transport
from portable_paths import foreign_path_message

SCHEMA_VERSION = "image-production-handoff/v2"
JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
RATIO_RE = re.compile(r"^[1-9][0-9]*:[1-9][0-9]*$")
SIZE_RE = re.compile(r"^[1-9][0-9]{2,4}x[1-9][0-9]{2,4}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ASPECT_TOLERANCE = 0.02
TOP_LEVEL_FIELDS = {
    "schema_version", "job_id", "operation", "prompt", "negative_prompt",
    "aspect_ratio", "image_size", "input_images", "output", "metadata",
}


class HandoffError(ValueError):
    """A secret-safe public handoff validation failure."""


def _portable_relative_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise HandoffError(f"{field} must be a non-empty string")
    path = PurePosixPath(value)
    foreign = foreign_path_message(value, field=field)
    if foreign is not None and (path.is_absolute() or "\\" in value or re.match(r"^[A-Za-z]:", value)):
        raise HandoffError(foreign)
    if (
        path.is_absolute()
        or value.startswith("~")
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value)
        or ".." in path.parts
    ):
        raise HandoffError(f"{field} must be a portable relative path")
    return value


def _image_reference(value: object, index: int) -> dict[str, str]:
    field = f"input_images[{index}]"
    if not isinstance(value, dict) or set(value) != {"path", "role"}:
        raise HandoffError(f"{field} must contain exactly path and role")
    raw_path = value["path"]
    if not isinstance(raw_path, str) or not raw_path or len(raw_path) > 1024:
        raise HandoffError(f"{field}.path must be a non-empty string of at most 1024 characters")
    if urlparse(raw_path).scheme:
        parsed = urlparse(raw_path)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username is not None:
            raise HandoffError(f"{field}.path URL must use https without embedded credentials")
        path = raw_path
    else:
        path = _portable_relative_path(raw_path, f"{field}.path")
    role = value["role"]
    if not isinstance(role, str) or not role.strip() or len(role) > 200:
        raise HandoffError(f"{field}.role must be a non-empty string of at most 200 characters")
    return {"path": path, "role": role}


def validate_handoff(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HandoffError("handoff must be a JSON object")
    unknown = set(value) - TOP_LEVEL_FIELDS
    if unknown:
        raise HandoffError("handoff contains unsupported fields")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise HandoffError(f"schema_version must be {SCHEMA_VERSION}")
    job_id = value.get("job_id")
    if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
        raise HandoffError("job_id must be 1-128 portable identifier characters")
    operation = value.get("operation")
    if operation not in {"generate", "edit"}:
        raise HandoffError("operation must be generate or edit")
    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
        raise HandoffError("prompt must be a non-empty string of at most 2000 characters")
    output = value.get("output")
    if not isinstance(output, dict) or set(output) != {"filename"}:
        raise HandoffError("output must contain exactly filename")
    output_filename = output["filename"]
    if (
        not isinstance(output_filename, str)
        or not re.fullmatch(r"[^/\\]+\.(?:png|jpg|jpeg|webp)", output_filename)
    ):
        raise HandoffError("output.filename must be a portable PNG, JPEG, or WebP basename")
    images = value.get("input_images", [])
    if not isinstance(images, list) or len(images) > 20:
        raise HandoffError("input_images must be an array with at most 20 items")
    normalized_images = [_image_reference(item, index) for index, item in enumerate(images)]
    if operation == "edit" and not normalized_images:
        raise HandoffError("edit handoffs require at least one input image")
    for field, pattern in (("aspect_ratio", RATIO_RE), ("image_size", SIZE_RE)):
        field_value = value.get(field)
        if field_value is not None and (not isinstance(field_value, str) or not pattern.fullmatch(field_value)):
            raise HandoffError(f"{field} has an invalid format")
    negative_prompt = value.get("negative_prompt")
    if negative_prompt is not None and (
        not isinstance(negative_prompt, str) or not negative_prompt.strip() or len(negative_prompt) > 1000
    ):
        raise HandoffError("negative_prompt must be a non-empty string of at most 1000 characters")
    metadata = value.get("metadata")
    if metadata is not None and (
        not isinstance(metadata, dict)
        or any(not isinstance(item, str) or len(item) > 500 for item in metadata.values())
    ):
        raise HandoffError("metadata values must be strings of at most 500 characters")
    normalized = dict(value)
    normalized["prompt"] = prompt
    normalized["output"] = {"filename": output_filename}
    normalized["input_images"] = normalized_images
    return normalized


def _transport_prompt(handoff: dict[str, Any]) -> str:
    constraints = []
    if handoff.get("negative_prompt"):
        constraints.append(f"Negative requirements: {handoff['negative_prompt']}")
    if handoff.get("aspect_ratio"):
        constraints.append(f"Requested aspect ratio: {handoff['aspect_ratio']}")
    if handoff.get("image_size"):
        constraints.append(f"Requested image size: {handoff['image_size']}")
    if not constraints:
        return handoff["prompt"]
    return handoff["prompt"] + "\n\n" + "\n".join(constraints)


def _png_dimensions(path: Path) -> tuple[int, int]:
    """Read width/height from the PNG IHDR header without decoding the image."""
    try:
        with path.open("rb") as handle:
            header = handle.read(24)
    except OSError as exc:
        raise HandoffError(f"delivered artifact could not be read: {path.name}") from exc
    if len(header) < 24 or not header.startswith(PNG_SIGNATURE) or header[12:16] != b"IHDR":
        raise HandoffError(f"delivered artifact is not a readable PNG: {path.name}")
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    if width <= 0 or height <= 0:
        raise HandoffError(f"delivered PNG reports non-positive dimensions: {path.name}")
    return width, height


def dimension_check(handoff: dict[str, Any], output: Path) -> dict[str, Any] | None:
    """Verify delivered PNG dimensions against the requested aspect_ratio/image_size.

    A requested aspect ratio is never claimed from the prompt token alone — the
    delivered pixels are the evidence. Returns None when the handoff requested
    neither field.
    """
    requested_ratio = handoff.get("aspect_ratio")
    requested_size = handoff.get("image_size")
    if not requested_ratio and not requested_size:
        return None
    width, height = _png_dimensions(output)
    check: dict[str, Any] = {"actual": f"{width}x{height}", "matched": True}
    if requested_size:
        check["requested_image_size"] = requested_size
        if requested_size != f"{width}x{height}":
            check["matched"] = False
    if requested_ratio:
        check["requested_aspect_ratio"] = requested_ratio
        ratio_w, ratio_h = (int(part) for part in requested_ratio.split(":"))
        expected = ratio_w / ratio_h
        if abs((width / height) - expected) > ASPECT_TOLERANCE * expected:
            check["matched"] = False
    return check


def consume_handoff(
    handoff_path: Path,
    output_root: Path,
    execute: bool = False,
    accept_dimension_drift: bool = False,
) -> dict[str, Any]:
    try:
        handoff = validate_handoff(json.loads(handoff_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise HandoffError("handoff could not be read as JSON") from exc
    if len(handoff["input_images"]) > 4:
        raise HandoffError("this executor supports at most four input images")
    if Path(handoff["output"]["filename"]).suffix.lower() != ".png":
        raise HandoffError("this executor requires a PNG output filename")
    image_paths: list[Path] = []
    for image in handoff["input_images"]:
        if urlparse(image["path"]).scheme:
            raise HandoffError("input image URLs must be materialized as relative local files before execution")
        image_paths.append((handoff_path.parent / image["path"]).resolve())
    output = (output_root / handoff["output"]["filename"]).resolve()
    root = output_root.resolve()
    if output != root and root not in output.parents:
        raise HandoffError("output.filename escapes output root")
    summary = transport.run(_transport_prompt(handoff), output, image_paths, execute)
    result = {
        "schema_version": handoff["schema_version"],
        "job_id": handoff["job_id"],
        "compiler_metadata": handoff.get("metadata", {}),
        "transport": summary,
    }
    if execute:
        check = dimension_check(handoff, output)
        if check is not None:
            result["dimension_check"] = check
            if not check["matched"] and not accept_dimension_drift:
                # The handoff contract forbids silently changing a requested behavior:
                # a dimension miss fails closed, with the artifact retained for inspection.
                raise HandoffError(
                    "delivered dimensions "
                    f"{check['actual']} do not satisfy the requested "
                    f"{'/'.join(filter(None, [handoff.get('aspect_ratio'), handoff.get('image_size')]))}; "
                    f"artifact retained at {output} — regenerate, or rerun with "
                    "--accept-dimension-drift to accept the deviation explicitly"
                )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path.cwd())
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--accept-dimension-drift",
        action="store_true",
        help="Record a requested-vs-delivered dimension mismatch in the result instead of failing closed.",
    )
    args = parser.parse_args(argv)
    try:
        print(json.dumps(
            consume_handoff(args.handoff, args.output_root, args.execute, args.accept_dimension_drift),
            indent=2,
        ))
    except (HandoffError, transport.TransportError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
