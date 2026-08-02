#!/usr/bin/env python3
"""Fail-closed transport for Codex CLI subscription image generation.

This module never reads auth files or calls private/API-key endpoints. Live execution
requires an explicit flag and approval environment marker; dry-run is the default.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
import shutil
import stat
import re
import subprocess
import sys
from typing import Mapping, Sequence
from codex_cli_resolver import CodexResolutionError, ResolvedCodex, resolve_codex_command
from mpw_prompt_adapter import MpwPromptError, compile_single_prompt

GENERATED_IMAGES_DIR = Path.home() / ".codex" / "generated_images"
DOWNLOADS_DIR = Path.home() / "Downloads"
REASONING_EFFORT = "medium"

CLI_TIMEOUT_SECONDS = 900


def cli_timeout_seconds() -> int:
    """Effective CLI timeout: IMGGEN2_CLI_TIMEOUT_SECONDS overrides the default when it is a positive integer."""
    raw = os.environ.get("IMGGEN2_CLI_TIMEOUT_SECONDS", "")
    try:
        value = int(raw)
    except ValueError:
        return CLI_TIMEOUT_SECONDS
    return value if value > 0 else CLI_TIMEOUT_SECONDS
_SESSION_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_SESSION_ID_KEYS = {"thread_id", "session_id", "threadId", "sessionId"}
QC_AXES = ("goal_fit", "text_accuracy", "material_realism", "layout")
OPTIONAL_QC_AXES = ("identity_consistency",)
QC_MINIMUM_AVERAGE = 4.0
QC_AXIS_FLOOR = 4.0
QC_DELTAS = {
    "goal_fit": "Clarify the subject, intended role, mood, palette, and composition.",
    "text_accuracy": (
        "Specify each copy string verbatim with its role and position; remove "
        "noncritical copy before retrying."
    ),
    "material_realism": "Clarify the material, surface texture, and reflectance behavior.",
    "layout": "Clarify the bands, grid, margins, and element positions.",
    "identity_consistency": (
        "re-lock the identity anchors — face geometry, hairline/part, distinctive "
        "marks — against the reference and regenerate only drifted panels."
    ),
}


def _slug(prompt: str, limit: int = 40) -> str:
    slug = "-".join(re.findall(r"[a-z0-9]+", prompt.lower()))[:limit].strip("-")
    return slug or "image"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S")


def _dedupe(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Too many output collisions for {path}")


def resolve_output(prompt: str, output: Path | None, batch_dir: Path | None) -> Path:
    """Single generation defaults to ~/Downloads; batch work uses a dated subfolder.

    An explicit --output always wins. --output and --batch-dir are mutually exclusive
    (enforced by the caller). Directories are created so validation can proceed.
    """
    if output is not None:
        return output.expanduser()
    filename = f"{_slug(prompt)}-{_timestamp()}.png"
    if batch_dir is not None:
        base = batch_dir.expanduser() / datetime.now().strftime("%Y%m%d")
    else:
        base = DOWNLOADS_DIR
    base.mkdir(parents=True, exist_ok=True)
    return _dedupe(base / filename)


class TransportError(RuntimeError):
    pass


def build_command(
    prompt: str,
    output: Path,
    images: Sequence[Path],
    codex_bin: str | Path | None = None,
    *,
    resolved_codex: ResolvedCodex | None = None,
) -> list[str]:
    try:
        resolved = resolved_codex or resolve_codex_command(codex_bin)
    except CodexResolutionError as exc:
        raise TransportError(str(exc)) from None
    codex = resolved.command
    instruction = (
        "Use Codex's built-in image_generation tool to create or edit exactly one image. "
        "If reference images are attached, use them as the basis for the edit or combination. "
        "Let Codex select the supported image model and leave the generated PNG in "
        "~/.codex/generated_images/<session_id>/. "
        "Do not use HTTP clients, API keys, browser/DOM automation, private APIs, "
        "or any fallback provider. "
        f"User image request: {prompt}"
    )
    command = [
        codex,
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--json",
        "--config",
        f'model_reasoning_effort="{REASONING_EFFORT}"',
        "--sandbox",
        "workspace-write",
        "--cd",
        str(output.parent),
    ]
    for image in images:
        command.extend(("--image", str(image)))
    # `--image <FILE>...` is variadic in Codex CLI. Without the explicit
    # option terminator it greedily consumes the positional prompt as another
    # image and exits with "No prompt provided via stdin".
    command.extend(("--", instruction))
    return command


def validate_request(prompt: str, output: Path, images: Sequence[Path]) -> None:
    if not prompt.strip():
        raise TransportError("Prompt must not be empty.")
    if output.suffix.lower() != ".png":
        raise TransportError("Output must use .png because the Codex imagegen artifact is a PNG.")
    if output.exists():
        raise TransportError(f"Refusing to overwrite existing output: {output}")
    if not output.parent.is_dir():
        raise TransportError(f"Output directory does not exist: {output.parent}")
    if len(images) > 4:
        raise TransportError("At most four reference images are supported.")
    for image in images:
        if not image.is_file():
            raise TransportError(f"Reference image is not a file: {image}")


def _not_evaluated_qc() -> dict[str, object]:
    return {
        "qc_status": "not_evaluated",
        "failed_axes": [],
        "deltas": {},
    }


def _normalized_qc_scores(axis_scores: Mapping[str, object]) -> dict[str, float]:
    expected = set(QC_AXES)
    optional = set(OPTIONAL_QC_AXES)
    actual = set(axis_scores)
    missing = expected - actual
    unexpected = actual - expected - optional
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing={sorted(missing)}")
        if unexpected:
            details.append(f"unexpected={sorted(unexpected)}")
        raise ValueError(
            f"QC scores must contain {QC_AXES} and may contain {OPTIONAL_QC_AXES}: "
            f"{', '.join(details)}"
        )
    scores: dict[str, float] = {}
    for axis in QC_AXES + OPTIONAL_QC_AXES:
        if axis not in axis_scores:
            continue
        value = axis_scores[axis]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"QC score for {axis} must be a number from 0 to 5.")
        score = float(value)
        if not 0.0 <= score <= 5.0:
            raise ValueError(f"QC score for {axis} must be a number from 0 to 5.")
        scores[axis] = score
    return scores


def evaluate_qc(
    axis_scores: Mapping[str, object], *, rendered_text_exists: bool
) -> dict[str, object]:
    """Evaluate supplied local or human QC scores without inspecting an image.

    Execution-time safety validation only; final visual QC, comparison, and
    selection authority belongs to the active review workflow.

    The canonical average uses only the four required axes. text_accuracy, when
    rendered, and optional identity_consistency, when supplied, must meet the floor.
    """
    if not isinstance(rendered_text_exists, bool):
        raise ValueError("rendered_text_exists must be a boolean.")
    scores = _normalized_qc_scores(axis_scores)
    average = sum(scores[axis] for axis in QC_AXES) / len(QC_AXES)
    average_passed = average >= QC_MINIMUM_AVERAGE
    text_floor_passed = (
        not rendered_text_exists or scores["text_accuracy"] >= QC_AXIS_FLOOR
    )
    identity_floor_passed = (
        "identity_consistency" not in scores
        or scores["identity_consistency"] >= QC_AXIS_FLOOR
    )
    qc_status = (
        "passed"
        if average_passed and text_floor_passed and identity_floor_passed
        else "failed"
    )

    failed_axes: list[str] = []
    if not average_passed:
        failed_axes.extend(axis for axis in QC_AXES if scores[axis] < QC_AXIS_FLOOR)
    if (
        rendered_text_exists
        and not text_floor_passed
        and "text_accuracy" not in failed_axes
    ):
        failed_axes.append("text_accuracy")
    if not identity_floor_passed:
        failed_axes.append("identity_consistency")

    return {
        "qc_status": qc_status,
        "average": average,
        "axis_scores": scores,
        "rendered_text_exists": rendered_text_exists,
        "failed_axes": failed_axes,
        "deltas": {axis: QC_DELTAS[axis] for axis in failed_axes},
    }


def evaluate_promo_qc(
    *,
    physical_type_subject_interaction: bool,
    generic_card_regression: bool,
    printed_meta_ui_not_literal: bool,
    color_count: int,
    finishing_device_count: int,
    korean_glyph_mask_safe: bool,
) -> dict[str, object]:
    """Evaluate promo-layout checks from local or human observations only."""
    booleans = (
        physical_type_subject_interaction,
        generic_card_regression,
        printed_meta_ui_not_literal,
        korean_glyph_mask_safe,
    )
    if not all(isinstance(value, bool) for value in booleans):
        raise ValueError("Promo boolean checks must be booleans.")
    if (
        isinstance(color_count, bool)
        or not isinstance(color_count, int)
        or isinstance(finishing_device_count, bool)
        or not isinstance(finishing_device_count, int)
    ):
        raise ValueError("Promo color and finishing-device counts must be integers.")

    checks = {
        "physical_type_subject_interaction": physical_type_subject_interaction,
        "generic_card_regression": not generic_card_regression,
        "printed_meta_ui_not_literal": printed_meta_ui_not_literal,
        "color_lock_2_to_3": 2 <= color_count <= 3,
        "finishing_devices_1_to_3": 1 <= finishing_device_count <= 3,
        "korean_glyph_mask_safety": korean_glyph_mask_safe,
    }
    failed_promo_checks = [name for name, passed in checks.items() if not passed]
    return {
        "promo_status": "passed" if not failed_promo_checks else "failed",
        "promo_checks": checks,
        "failed_promo_checks": failed_promo_checks,
    }


def plan_qc_regeneration(
    output: Path,
    qc_report: Mapping[str, object],
    promo_report: Mapping[str, object] | None = None,
    *,
    promotional: bool = False,
) -> dict[str, object]:
    """Plan one-output regeneration from a QC report without touching the file.

    Execution-time recovery planning only; final acceptance authority stays
    with the active review workflow.
    """
    if not isinstance(promotional, bool):
        raise ValueError("promotional must be a boolean.")
    if promotional and promo_report is None:
        raise ValueError("Promotional outputs require a promo QC report.")
    qc_status = qc_report.get("qc_status")
    if qc_status not in {"passed", "failed"}:
        raise ValueError("QC report must have a passed or failed qc_status.")
    raw_failed_axes = qc_report.get("failed_axes", [])
    if not isinstance(raw_failed_axes, (list, tuple)):
        raise ValueError("QC report failed_axes must be a list or tuple.")
    failed_axes = list(raw_failed_axes)
    if any(axis not in QC_AXES + OPTIONAL_QC_AXES for axis in failed_axes):
        raise ValueError("QC report contains an unknown failed axis.")

    promo_status = "not_evaluated"
    failed_promo_checks: list[object] = []
    if promo_report is not None:
        promo_status = promo_report.get("promo_status")
        if promo_status not in {"passed", "failed"}:
            raise ValueError("Promo report must have a passed or failed promo_status.")
        raw_failed_promo_checks = promo_report.get("failed_promo_checks", [])
        if not isinstance(raw_failed_promo_checks, (list, tuple)):
            raise ValueError("Promo report failed_promo_checks must be a list or tuple.")
        failed_promo_checks = list(raw_failed_promo_checks)

    regenerate = qc_status == "failed" or promo_status == "failed"
    return {
        "qc_status": qc_status,
        "promo_status": promo_status,
        "failed_axes": failed_axes,
        "deltas": {axis: QC_DELTAS[axis] for axis in failed_axes},
        "failed_promo_checks": failed_promo_checks,
        "regenerate_outputs": [str(output)] if regenerate else [],
    }


def _resolved_provenance(resolved: object) -> dict[str, object]:
    provenance = getattr(resolved, "provenance", None)
    if isinstance(provenance, Mapping):
        return dict(provenance)
    command = getattr(resolved, "command", None)
    source = getattr(resolved, "source", "provided")
    version = getattr(resolved, "version", [])
    return {
        "path": str(command),
        "source": str(source),
        "version": list(version) if isinstance(version, tuple) else version,
    }

def request_summary(
    command: Sequence[str],
    output: Path,
    images: Sequence[Path],
    codex_provenance: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "transport": "official-codex-cli-subscription",
        "transport_state": "dry_run",
        "requested_model": None,
        "observed_model": None,
        "reasoning_effort": REASONING_EFFORT,
        "output": str(output),
        "reference_count": len(images),
        "command": ["<prompt>" if item.startswith("User image request:") else item for item in command[:-1]] + ["<image-instruction>"],
        "codex_provenance": dict(codex_provenance or {}),
        "live": False,
        "model_identity_attested": False,
        **_not_evaluated_qc(),
    }


def _pngs_under(directory: Path) -> set[Path]:
    return {
        path.resolve()
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() == ".png"
    }


def generated_pngs(root: Path | None = None) -> set[Path]:
    root = GENERATED_IMAGES_DIR if root is None else root
    if not root.is_dir():
        return set()
    return _pngs_under(root)


def session_ids_in_cli(cli_output: str) -> set[str]:
    """Extract UUIDs only from structured session/thread identity fields."""
    found: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if (
                    key in _SESSION_ID_KEYS
                    and isinstance(child, str)
                    and _SESSION_ID_RE.fullmatch(child)
                ):
                    found.add(child)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for line in (cli_output or "").splitlines():
        try:
            visit(json.loads(line))
        except (json.JSONDecodeError, TypeError):
            continue
    return found


def session_pngs(cli_output: str, root: Path | None = None) -> set[Path]:
    """Return PNGs physically contained by session dirs named in CLI output."""
    root = GENERATED_IMAGES_DIR if root is None else root
    if not root.is_dir():
        return set()
    resolved_root = root.resolve()
    found: set[Path] = set()
    for session_id in session_ids_in_cli(cli_output):
        session_dir = root / session_id
        if not session_dir.is_dir():
            continue
        resolved_session_dir = session_dir.resolve()
        try:
            resolved_session_dir.relative_to(resolved_root)
        except ValueError:
            continue
        for artifact in _pngs_under(session_dir):
            try:
                artifact.relative_to(resolved_session_dir)
            except ValueError:
                continue
            found.add(artifact)
    return found


def select_fresh_session_png(
    cli_output: str, before_snapshot: set[Path], root: Path | None = None
) -> Path | None:
    """Select one new, non-empty PNG from a session named by this invocation."""
    before = {path.resolve() for path in before_snapshot}
    fresh: list[tuple[int, Path]] = []
    for artifact in session_pngs(cli_output, root):
        if artifact in before:
            continue
        try:
            metadata = artifact.stat()
        except OSError:
            continue
        if metadata.st_size > 0:
            fresh.append((metadata.st_mtime_ns, artifact))
    return max(fresh, key=lambda candidate: candidate[0])[1] if fresh else None


def copy_png_exclusive(source: Path, output: Path) -> int:
    """Copy one stable regular file without following a replaced symlink or overwriting."""
    source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    destination_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    source_fd: int | None = None
    destination_created = False
    try:
        source_fd = os.open(source, source_flags)
        with os.fdopen(source_fd, "rb", closefd=True) as source_stream:
            source_fd = None
            before = os.fstat(source_stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
                raise TransportError("Selected session artifact is not a non-empty regular file.")
            try:
                destination_fd = os.open(output, destination_flags, 0o600)
            except FileExistsError:
                raise TransportError(f"Refusing to overwrite existing output: {output}") from None
            destination_created = True
            with os.fdopen(destination_fd, "wb", closefd=True) as output_stream:
                shutil.copyfileobj(source_stream, output_stream)
                output_stream.flush()
                os.fsync(output_stream.fileno())
            after = os.fstat(source_stream.fileno())
            stable = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            copied_size = output.stat().st_size
            if not stable or copied_size != before.st_size:
                raise TransportError("Session artifact changed while it was being copied.")
            return copied_size
    except TransportError:
        if destination_created:
            output.unlink(missing_ok=True)
        raise
    except OSError as exc:
        if destination_created:
            output.unlink(missing_ok=True)
        raise TransportError(f"Could not copy the verified session artifact: {exc.strerror or exc.__class__.__name__}.") from None
    finally:
        if source_fd is not None:
            os.close(source_fd)


def classify_cli_failure(stdout: str, stderr: str) -> str:
    """Return a secret-free error category without retaining subprocess output."""
    text = f"{stdout}\n{stderr}".lower()
    rules = (
        ("cli_argument_error", r"no prompt provided via stdin"),
        ("model_unavailable", r"model.{0,80}(not found|unknown|unsupported|unavailable|does not exist|invalid)"),
        ("authentication_required", r"(not logged in|login required|authentication required|unauthorized|invalid authentication)"),
        ("entitlement_denied", r"(not entitled|entitlement|does not have access|permission denied|forbidden)"),
        ("rate_limited", r"(rate limit|too many requests|usage limit|quota exceeded)"),
        ("image_tool_unavailable", r"(image_generation|image generation|imagegen).{0,80}(unavailable|unsupported|disabled|not enabled|not found|missing)"),
        (
            "moderation_rejected",
            r"(content polic(y|ies)|policy (restriction|violation)|"
            r"(unable|can't|cannot|not able|won't be able) to (generate|create|produce|make)\b[^.\n]{0,60}\bimage)",
        ),
    )
    for category, pattern in rules:
        if re.search(pattern, text):
            return category
    return "unknown_cli_failure"



def run(
    prompt: str,
    output: Path,
    images: Sequence[Path],
    execute: bool = False,
    codex_bin: str | Path | None = None,
    *,
    codex_provenance: Mapping[str, object] | None = None,
) -> dict[str, object]:
    output = output.expanduser().resolve()
    refs = [image.expanduser().resolve() for image in images]
    validate_request(prompt, output, refs)
    try:
        if codex_provenance is None:
            resolved = resolve_codex_command(codex_bin)
        else:
            raw_path = codex_provenance.get("path")
            raw_source = codex_provenance.get("source")
            raw_version = codex_provenance.get("version")
            if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
                raise CodexResolutionError("Codex provenance path must be absolute.")
            if not isinstance(raw_source, str) or not isinstance(raw_version, (list, tuple)):
                raise CodexResolutionError("Codex provenance is malformed.")
            if len(raw_version) != 3 or any(
                isinstance(part, bool) or not isinstance(part, int) for part in raw_version
            ):
                raise CodexResolutionError("Codex provenance version is malformed.")
            resolved = ResolvedCodex(
                command=str(Path(raw_path).resolve(strict=False)),
                source=raw_source,
                version=tuple(raw_version),  # type: ignore[arg-type]
            )
            if codex_bin is not None and str(Path(codex_bin).resolve(strict=False)) != resolved.command:
                raise CodexResolutionError("Codex executable path does not match its provenance.")
    except CodexResolutionError as exc:
        raise TransportError(str(exc)) from None
    command = build_command(prompt, output, refs, resolved_codex=resolved)
    summary = request_summary(command, output, refs, _resolved_provenance(resolved))
    if not execute:
        return summary
    # The caller's explicit image-generation request authorizes this bounded invocation.
    before = generated_pngs()
    timeout_seconds = cli_timeout_seconds()
    try:
        completed = subprocess.run(
            command,
            cwd=output.parent,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        raise TransportError(
            f"Codex CLI timed out after {timeout_seconds}s; no output retained."
        ) from None
    cli_output = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode != 0:
        category = classify_cli_failure(completed.stdout, completed.stderr)
        raise TransportError(
            f"Codex CLI failed with exit code {completed.returncode}; category={category}; "
            "any artifact from the failed invocation was rejected; raw output withheld to protect secrets."
        )
    session_ids = session_ids_in_cli(cli_output)
    generated = select_fresh_session_png(cli_output, before)
    if generated is None:
        # A moderation refusal exits 0 with no artifact; distinguish it so batch
        # ledgers and retry manifests can target rejected cuts for prompt rework.
        if classify_cli_failure(completed.stdout, completed.stderr) == "moderation_rejected":
            raise TransportError(
                "Codex declined the request; category=moderation_rejected; no artifact was "
                "produced. Rework this prompt with neutral campaign/editorial language and "
                "retry only this job; never escalate explicitness to bypass moderation."
            )
        session_reason = (
            "no session/thread ID was reported"
            if not session_ids
            else "no fresh PNG was created in a reported session directory"
        )
        raise TransportError(
            "Codex CLI completed but did not produce a fresh session-scoped PNG; "
            f"{session_reason}."
        )
    copied_bytes = copy_png_exclusive(generated, output)
    summary.update(
        {
            "live": True,
            "transport_state": "succeeded",
            "bytes": copied_bytes,
            "source_artifact": str(generated),
            "cli_exit_code": completed.returncode,
            "warning": None,
        }
    )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", type=Path, help="Explicit output path; wins over defaults")
    parser.add_argument("--batch-dir", type=Path, help="Folder-based batch root; outputs go to a dated subfolder inside it")
    parser.add_argument("--image", action="append", default=[], type=Path)
    parser.add_argument("--execute", action="store_true", help="Perform the approved live call")
    parser.add_argument("--codex-bin", type=Path, help="Explicit official Codex CLI executable")
    parser.add_argument("--mpw", choices=("auto", "off", "required"), default="auto", help="MPW prompt enhancement for simple text-only generation")
    parser.add_argument("--mpw-root", type=Path, help="Explicit MPW installation root")
    args = parser.parse_args(argv)
    if args.output is not None and args.batch_dir is not None:
        print(json.dumps({"error": "Use either --output or --batch-dir, not both."}), file=sys.stderr)
        return 2
    try:
        effective_prompt = args.prompt
        mpw_compiled = False
        if not args.image:
            effective_prompt, mpw_compiled = compile_single_prompt(args.prompt, mode=args.mpw, mpw_root=args.mpw_root)
        output = resolve_output(args.prompt, args.output, args.batch_dir)
        result = run(effective_prompt, output, args.image, args.execute, args.codex_bin)
        result["mpw_compiled"] = mpw_compiled
        print(json.dumps(result, indent=2))
    except (TransportError, MpwPromptError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
