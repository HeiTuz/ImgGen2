#!/usr/bin/env python3
"""ImgGen2-owned Wan transport that leaves Hermes-native image_gen routing untouched."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

HERMES_HOME = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser().resolve()
PLUGIN_PATH = HERMES_HOME / "plugins" / "alibaba-token-plan-media" / "__init__.py"
DEFAULT_RUN_ROOT = HERMES_HOME / "artifacts" / "imggen2"


class TransportError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prompt_digest(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def validate(prompt: str, reference_url: str | None, model: str, aspect_ratio: str) -> None:
    if not prompt.strip():
        raise TransportError("Prompt must not be empty")
    if model not in {"wan2.7-image", "wan2.7-image-pro"}:
        raise TransportError(f"Unsupported Wan model: {model}")
    if aspect_ratio not in {"landscape", "square", "portrait"}:
        raise TransportError(f"Unsupported aspect ratio: {aspect_ratio}")
    if reference_url and urlparse(reference_url).scheme not in {"http", "https"}:
        raise TransportError("Wan reference input must be a public HTTP(S) URL")


def _load_provider():
    if not PLUGIN_PATH.is_file():
        raise TransportError(f"Alibaba media plugin is not installed: {PLUGIN_PATH}")
    spec = importlib.util.spec_from_file_location("imggen2_alibaba_media", PLUGIN_PATH)
    if spec is None or spec.loader is None:
        raise TransportError("Could not load Alibaba media plugin")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    provider = module.AlibabaTokenPlanImageProvider()
    if not provider.is_available():
        raise TransportError("QWEN_TOKEN_PLAN_API_KEY is not configured")
    return provider


def run(prompt: str, *, reference_url: str | None = None, model: str = "wan2.7-image", aspect_ratio: str = "portrait", execute: bool = False, run_root: Path = DEFAULT_RUN_ROOT, provider: Any = None) -> dict[str, Any]:
    validate(prompt, reference_url, model, aspect_ratio)
    run_id = f"wan-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{_prompt_digest(prompt)[:8]}"
    if not execute:
        return {"transport_state": "dry_run", "run_id": run_id, "provider": "alibaba-token-plan", "model": model, "aspect_ratio": aspect_ratio, "reference_count": int(bool(reference_url)), "input_role": "identity_reference" if reference_url else "none", "prompt_digest": _prompt_digest(prompt), "hermes_native_config_touched": False}
    backend = provider or _load_provider()
    # A QC retry is a fresh generation from the immutable original reference.
    # Never pass a prior output as image_url: that silently turns repair into
    # chained image editing and compounds visual damage.
    result = backend.generate(prompt, aspect_ratio, reference_image_urls=[reference_url] if reference_url else None, model=model)
    if not result.get("success"):
        raise TransportError(str(result.get("error") or "Wan generation failed"))
    artifact = Path(str(result["image"])).expanduser().resolve()
    if not artifact.is_file() or artifact.stat().st_size <= 0:
        raise TransportError("Wan provider returned a missing or empty artifact")
    run_dir = run_root.expanduser().resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    record = {"schema_version": 1, "run_id": run_id, "created_at": _now(), "transport": "imggen2-alibaba-token-plan", "provider": "alibaba-token-plan", "model": str(result.get("model") or model), "artifact_id": artifact.stem, "artifact_path": str(artifact), "artifact_sha256": _sha256(artifact), "artifact_bytes": artifact.stat().st_size, "prompt": prompt, "prompt_digest": _prompt_digest(prompt), "aspect_ratio": aspect_ratio, "reference_summary": {"count": int(bool(reference_url)), "input_kind": "public_https" if reference_url else "none", "input_role": "identity_reference" if reference_url else "none", "regeneration_parent_artifact_id": None}, "hermes_native_config_touched": False, "qc_status": "pending_review"}
    provenance = run_dir / "provenance.json"
    provenance.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**record, "provenance_path": str(provenance), "transport_state": "succeeded"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--reference-url", help="Immutable original reference; never a prior generated artifact")
    parser.add_argument("--model", default="wan2.7-image", choices=("wan2.7-image", "wan2.7-image-pro"))
    parser.add_argument("--aspect-ratio", default="portrait", choices=("landscape", "square", "portrait"))
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.prompt, reference_url=args.reference_url, model=args.model, aspect_ratio=args.aspect_ratio, execute=args.execute, run_root=args.run_root), ensure_ascii=False))
        return 0
    except TransportError as exc:
        print(json.dumps({"transport_state": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
