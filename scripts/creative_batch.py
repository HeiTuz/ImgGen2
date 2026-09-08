#!/usr/bin/env python3
"""Reusable MPW -> ImgGen2 bulk ideation runner with clean final-only output."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Callable, Mapping

import codex_subscription_batch as batch
from mpw_prompt_adapter import MpwPromptError, compile_manifest
from image_artifacts import ArtifactError, inspect_png


class CreativeBatchError(RuntimeError):
    pass


def _workspace_for(output_root: Path, prompt: str, style: str, count: int, seed: int | None) -> Path:
    identity = json.dumps({"prompt": prompt, "style": style, "count": count, "seed": seed}, ensure_ascii=False, sort_keys=True)
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return output_root.parent / f".{output_root.name}.imggen-work-{suffix}"


def _owned_pngs(manifest: Path, root: Path) -> list[Path]:
    jobs, manifest_hash = batch.load_manifest(manifest, root)
    ledger = batch.load_ledger(root / batch.LEDGER_NAME)
    batch.recover_and_validate_ledger(ledger, jobs, manifest_hash)
    if batch.build_summary(ledger)["completion_state"] != "complete":
        raise CreativeBatchError("Ledger is not complete; publication is blocked")
    return [job.output for job in jobs]


def _publish(images: list[Path], output_root: Path) -> None:
    if output_root.exists() and any(output_root.iterdir()):
        raise CreativeBatchError(f"Final output root is not empty: {output_root}")
    staging = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.publish-", dir=output_root.parent))
    try:
        seen: set[str] = set()
        for image in images:
            if image.name in seen:
                raise CreativeBatchError(f"Duplicate final image filename: {image.name}")
            seen.add(image.name)
            expected = inspect_png(image)
            destination = staging / image.name
            with image.open("rb") as source, destination.open("xb") as target:
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
            if inspect_png(destination) != expected:
                raise CreativeBatchError("Final image changed during publication")
        if output_root.exists():
            output_root.rmdir()
        staging.replace(output_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def run_creative_batch(
    prompt: str,
    style: str,
    count: int,
    output_root: Path,
    *,
    execute: bool = False,
    mpw_root: Path | None = None,
    seed: int | None = None,
    workers: str = "auto",
    start: int = 3,
    hard_cap: int = 8,
    ramp_every: int = 3,
    ram_per_worker_gb: float = 0.5,
    codex_bin: str | Path | None = None,
    batch_runner: Callable[..., Mapping[str, object]] = batch.run_batch,
) -> dict[str, object]:
    if not prompt.strip():
        raise CreativeBatchError("Prompt must not be empty.")
    if not 1 <= count <= 1000:
        raise CreativeBatchError("Count must be between 1 and 1000.")
    output_root = output_root.expanduser().resolve()
    if execute and output_root.exists():
        if not output_root.is_dir() or any(output_root.iterdir()):
            raise CreativeBatchError(f"Final output root is not empty: {output_root}")
    workspace = _workspace_for(output_root, prompt, style, count, seed)
    runner_options = dict(
        workers=workers, start=start, hard_cap=hard_cap, ramp_every=ramp_every,
        ram_per_worker_gb=ram_per_worker_gb, codex_bin=codex_bin,
    )
    if not execute:
        # A plan must never delete a failed live run's resumable state. Reuse
        # its exact compiled manifest, but give planning an isolated workspace.
        retained = workspace.exists()
        try:
            with tempfile.TemporaryDirectory(prefix="imggen-plan-") as tmp:
                plan_root = Path(tmp)
                plan_manifest = plan_root / "variations.jsonl"
                existing_manifest = workspace / "variations.jsonl"
                if existing_manifest.is_file():
                    shutil.copyfile(existing_manifest, plan_manifest)
                else:
                    compile_manifest(prompt, style, count, plan_manifest, mpw_root=mpw_root, seed=seed, output_prefix="images")
                summary = dict(batch_runner(
                    plan_manifest, plan_root / "generated", execute=False, **runner_options,
                ))
            return {
                "mode": "dry_run", "count": count, "mpw_compiled": True,
                "qc_required": False, "final_output_root": str(output_root),
                "batch_plan": summary, "workspace_retained": retained,
            }
        except (batch.BatchError, MpwPromptError, OSError) as exc:
            raise CreativeBatchError(f"Dry-run failed: {exc}; existing resume state was preserved.") from None
    generated = workspace / "generated"
    manifest = workspace / "variations.jsonl"
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        if not manifest.exists():
            compile_manifest(prompt, style, count, manifest, mpw_root=mpw_root, seed=seed, output_prefix="images")
        summary = dict(batch_runner(
            manifest,
            generated,
            execute=True,
            **runner_options,
        ))
        counts = summary.get("counts", {})
        succeeded = counts.get("succeeded", 0) if isinstance(counts, dict) else 0
        if succeeded != count or summary.get("awaiting_qc") or summary.get("awaiting_pilot_qc"):
            raise CreativeBatchError(f"Batch incomplete ({succeeded}/{count}); workspace retained for resume: {workspace}")
        images = _owned_pngs(manifest, generated)
        if len(images) != count:
            raise CreativeBatchError(f"Expected {count} final PNGs, found {len(images)}; workspace retained: {workspace}")
        _publish(images, output_root)
        shutil.rmtree(workspace)
        return {
            "mode": "live",
            "count": count,
            "mpw_compiled": True,
            "qc_required": False,
            "final_output_root": str(output_root),
            "workspace_retained": False,
            "files": [path.name for path in sorted(output_root.iterdir())],
        }
    except (batch.BatchError, MpwPromptError, ArtifactError, OSError, CreativeBatchError) as exc:
        if isinstance(exc, CreativeBatchError):
            raise
        raise CreativeBatchError(f"{exc}; workspace retained for resume: {workspace}") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--style", default="")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--mpw-root", type=Path)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--workers", default="auto")
    parser.add_argument("--start", type=int, default=3)
    parser.add_argument("--hard-cap", type=int, default=8)
    parser.add_argument("--ramp-every", type=int, default=3)
    parser.add_argument("--ram-per-worker-gb", type=float, default=0.5)
    parser.add_argument("--codex-bin", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_creative_batch(
            args.prompt, args.style, args.count, args.output_root,
            execute=args.execute, mpw_root=args.mpw_root, seed=args.seed,
            workers=args.workers, start=args.start, hard_cap=args.hard_cap,
            ramp_every=args.ramp_every, ram_per_worker_gb=args.ram_per_worker_gb,
            codex_bin=args.codex_bin,
        )
    except CreativeBatchError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
