#!/usr/bin/env python3
"""Single text-only generation with MPW enhancement required."""
from pathlib import Path
import importlib.util
import sys

if __name__ == "__main__":
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("heituz_skill_single_transport_example", scripts / "codex_subscription_transport.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the packaged single-image transport.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    argv = list(sys.argv[1:])
    if "--prompt" not in argv and not any(value.startswith("--prompt=") for value in argv):
        argv.extend(("--prompt", "비 오는 밤 편의점 창가의 파란 세라믹 컵"))
    if "--output" not in argv and not any(value.startswith("--output=") for value in argv):
        argv.extend(("--output", str(Path.cwd() / "single-mpw-enhanced.png")))
    if "--mpw" not in argv and not any(value.startswith("--mpw=") for value in argv):
        argv.extend(("--mpw", "required"))
    raise SystemExit(module.main(argv))
