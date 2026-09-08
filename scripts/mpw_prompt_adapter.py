#!/usr/bin/env python3
"""Locate MPW and compile simple or bulk image prompts without residue."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Literal
try:
    import mpw_root
except ModuleNotFoundError:
    from scripts import mpw_root
MpwMode = Literal["auto", "off", "required"]


class MpwPromptError(RuntimeError):
    pass


def discover_mpw_root(explicit: Path | None = None) -> Path | None:
    """Return a shared-resolver installation only when its compiler is present."""
    try:
        root = (
            mpw_root.validate_mpw_root(explicit, source="--mpw-root")
            if explicit is not None
            else mpw_root.resolve_mpw_root()
        )
    except RuntimeError as exc:
        raise MpwPromptError(str(exc)) from None
    if root is not None and (root / "scripts" / "compile_image_variations.py").is_file():
        return root
    return None


def compile_manifest(
    prompt: str,
    style: str,
    count: int,
    output: Path,
    *,
    mpw_root: Path | None = None,
    seed: int | None = None,
    output_prefix: str = "images",
) -> Path:
    root = discover_mpw_root(mpw_root)
    if root is None:
        raise MpwPromptError("MPW variation compiler is unavailable; install/update MPW or pass --mpw-root.")
    compiler = root / "scripts" / "compile_image_variations.py"
    output.parent.mkdir(parents=True, exist_ok=True)
    request = {"concept": prompt, "style": style, "output_prefix": output_prefix, "locks": {}}
    with tempfile.TemporaryDirectory(prefix=".imggen-compile-", dir=output.parent) as tmp:
        request_path = Path(tmp) / "request.json"
        compiled_path = Path(tmp) / "compiled.jsonl"
        request_path.write_text(json.dumps(request, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        command = [sys.executable, str(compiler), "--request", str(request_path), "--count", str(count), "--output", str(compiled_path)]
        if seed is not None:
            command.extend(("--seed", str(seed)))
        try:
            completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=120)
            if completed.returncode != 0:
                raise MpwPromptError(f"MPW variation compiler failed (exit {completed.returncode}); output preserved.")
            rows = [json.loads(line) for line in compiled_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if len(rows) != count or any(not isinstance(row, dict) or not isinstance(row.get("full_prompt", row.get("prompt")), str) or not row.get("full_prompt", row.get("prompt", "")).strip() for row in rows):
                raise MpwPromptError("MPW returned an incomplete or invalid prompt manifest")
            # Publish only after a complete compile. Never delete an older manifest on failure.
            compiled_path.replace(output)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise MpwPromptError("MPW compilation failed or timed out; prior output preserved.") from exc
    return output


def compile_single_prompt(prompt: str, *, mode: MpwMode = "auto", mpw_root: Path | None = None) -> tuple[str, bool]:
    if mode == "off":
        return prompt, False
    root = discover_mpw_root(mpw_root)
    if root is None:
        if mode == "required":
            raise MpwPromptError("--mpw required but MPW variation compiler was not found.")
        return prompt, False
    with tempfile.TemporaryDirectory(prefix="imggen-mpw-single-") as tmp:
        manifest = Path(tmp) / "single.jsonl"
        compile_manifest(prompt, "", 1, manifest, mpw_root=root, output_prefix="images")
        try:
            row = json.loads(manifest.read_text(encoding="utf-8").splitlines()[0])
            compiled = row["full_prompt"]
        except (IndexError, KeyError, json.JSONDecodeError) as exc:
            raise MpwPromptError("MPW returned an invalid single-prompt manifest.") from exc
    if not isinstance(compiled, str) or not compiled.strip():
        raise MpwPromptError("MPW returned an empty compiled prompt.")
    return compiled.strip(), True
