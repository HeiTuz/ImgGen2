#!/usr/bin/env python3
"""Shared entrypoint for packaged creative-batch examples."""
from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
from typing import Sequence


def _has_option(argv: Sequence[str], option: str) -> bool:
    return option in argv or any(value.startswith(option + "=") for value in argv)


def run_preset(*, slug: str, prompt: str, style: str, count: int, argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    defaults = (
        ("--prompt", prompt),
        ("--style", style),
        ("--count", str(count)),
        ("--output-root", str(Path.cwd() / slug)),
    )
    for option, value in defaults:
        if not _has_option(args, option):
            args.extend((option, value))
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("heituz_skill_creative_batch_example", scripts / "creative_batch.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the packaged creative batch runner.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main(args)
