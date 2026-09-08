#!/usr/bin/env python3
"""Prepare and publish a validated apparel shared-folder batch."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import math
from image_artifacts import ArtifactError, inspect_png
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
import time
from pathlib import Path
from typing import Any

try:
    import apparel_three_fullset as fullset
except ImportError:
    _spec = importlib.util.spec_from_file_location("apparel_three_fullset", Path(__file__).with_name("apparel_three_fullset.py"))
    assert _spec and _spec.loader
    fullset = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = fullset
    _spec.loader.exec_module(fullset)
try:
    from portable_paths import PathCompatibilityError, is_symlink_or_reparse, normalize_local_path
except ImportError:
    _spec = importlib.util.spec_from_file_location("portable_paths", Path(__file__).with_name("portable_paths.py"))
    assert _spec and _spec.loader
    _paths = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = _paths
    _spec.loader.exec_module(_paths)
    PathCompatibilityError = _paths.PathCompatibilityError
    is_symlink_or_reparse = _paths.is_symlink_or_reparse
    normalize_local_path = _paths.normalize_local_path

SCHEMA_VERSION = 1
MODE = "apparel-product-correction"
_TIMESTAMP = re.compile(r"^\d{8}_\d{6}$")
_RESULT = re.compile(r"^AI_RESULT_[A-Za-z0-9_-]+$")
_ROLE_PATTERNS = ((re.compile(r"^f([0-9]+)$"), "front_variant", "front-variant"), (re.compile(r"^b([0-9]+)$"), "back_variant", "back-variant"), (re.compile(r"^c([0-9]+)$"), "color_front", "color-front"), (re.compile(r"^d([0-9]+)$"), "fabric_detail", "fabric-detail"), (re.compile(r"^s([0-9]+)$"), "composite_source", "composite-source"))
CORRECTION_CONTRACT = ("Preserve the product's original design, color, material cues, trims, graphics, and details; only mild, natural fit cleanup where folds/collapse came from the shoot setup; remove mannequins, hangers, racks, stands, hands/people, text, and watermarks when not part of the product; never redesign the garment or invent unsupported construction.")
QC_CONTRACT = ("Independent Vision QC must reject retained supports, excessive fit changes, altered design/color/material/trim/graphic details, and invented garment construction; verify role mapping, construction evidence, occlusions, and product grouping against the complete source inventory.")
FOLDER_MASTER = "Apparel product correction: create faithful clean product imagery from the complete validated folder inventory."


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _blocked(message: str) -> fullset.ContractError:
    return fullset.ContractError("blocked: " + message)


def _canonical_filesystem_path(raw: str, *, field: str) -> Path:
    """Normalize user input once and keep the resulting Path for all filesystem work."""
    path = Path(normalize_local_path(raw, field=field)).expanduser()
    if os.name == "nt" and str(path).startswith("\\\\"):
        return path
    return path.resolve()


def source_folder(raw: str) -> Path:
    path = _canonical_filesystem_path(raw, field="--input-dir")
    if not path.exists() or not path.is_dir():
        raise _blocked(f"--input-dir is not an existing directory: {path}")
    if is_symlink_or_reparse(path):
        raise _blocked(f"--input-dir must not be a symlink/junction/reparse point: {path}")
    if not path.name or "/" in path.name or "\\" in path.name:
        raise _blocked("--input-dir has an invalid folder name")
    return path


def _inventory(source: Path) -> tuple[list[Path], list[dict[str, str]], list[str]]:
    candidates: list[Path] = []
    skipped: list[dict[str, str]] = []
    results: list[str] = []
    blocked: list[str] = []
    hidden_images: list[str] = []
    artifacts = {"thumbs.db", "desktop.ini", "ehthumbs.db"}
    for entry in sorted(source.iterdir(), key=lambda item: item.name):
        name = entry.name
        if is_symlink_or_reparse(entry):
            blocked.append(name)
            continue
        if entry.is_dir():
            if re.match(r"^AI_RESULT_", name):
                results.append(name)
            else:
                skipped.append({"name": name, "reason": "subdirectory-not-inventoried"})
            continue
        suffix = entry.suffix.casefold()
        if name.casefold() in artifacts or name.startswith(".") or suffix == ".tmp":
            if (name.startswith(".") or name.startswith("._")) and suffix in fullset.SOURCE_IMAGE_SUFFIXES:
                hidden_images.append(name)
            else:
                skipped.append({"name": name, "reason": "ordinary-artifact"})
        elif suffix in fullset.SOURCE_IMAGE_SUFFIXES:
            candidates.append(entry)
        else:
            skipped.append({"name": name, "reason": "unsupported-file-type"})
    if blocked:
        raise _blocked(f"symlink/junction/reparse entries in source folder: {blocked}")
    if hidden_images:
        raise _blocked(f"hidden image files in source folder; remove or rename: {hidden_images}")
    if not candidates:
        raise _blocked(f"no supported source images in {source}")
    return candidates, skipped, results


def role_map(candidates: list[Path]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    unknown: list[str] = []
    slots: dict[str, str] = {}
    for path in candidates:
        norm = unicodedata.normalize("NFC", path.stem)
        token, separator, descriptor = norm.partition("_")
        token = token.casefold()
        record: dict[str, str] | None = None
        if token == "f1":
            record = {"file": path.name, "role": "color_front", "shot_role": "front", "color_identity": "default"}
        elif token == "b1":
            record = {"file": path.name, "role": "main_back", "shot_role": "back"}
        else:
            for pattern, role, shot_role in _ROLE_PATTERNS:
                match = pattern.fullmatch(token)
                if match and (token[0] not in "fb" or int(match.group(1)) >= 2):
                    record = {"file": path.name, "role": role, "shot_role": shot_role}
                    if role == "color_front":
                        record["color_identity"] = token
                    break
        if record is None:
            unknown.append(path.name)
            continue
        if token in slots:
            raise _blocked(f"conflicting source filenames map to the same role slot: {sorted([slots[token], path.name])}")
        slots[token] = path.name
        if separator and descriptor:
            record["descriptor"] = descriptor
        records.append(record)
    if unknown:
        raise _blocked("unknown source filenames (expected f1/b1/fN/bN/cN/dN/sN with optional _descriptor): " + str(sorted(unknown)))
    if not any(row["role"] == "color_front" for row in records):
        raise _blocked("no front cut (f1 or cN) found; color identities cannot be established")
    return records


def _prompt(record: dict[str, str]) -> str:
    sentences = {"front": "Correct the front product cut on a clean product presentation.", "back": "Correct the back product cut on a clean product presentation.", "front-variant": "Correct this front variant while preserving its specific construction.", "back-variant": "Correct this back variant while preserving its specific construction.", "color-front": "Correct this color front cut while preserving its opaque color identity.", "fabric-detail": "Correct this fabric/detail source while preserving material and construction evidence.", "composite-source": "Correct this composite source while preserving all supported product evidence."}
    return "IMAGE. " + sentences[record["shot_role"]] + " " + CORRECTION_CONTRACT


def _result_name(value: str | None, timestamp: str) -> str:
    name = f"AI_RESULT_{timestamp}" if value in (None, "auto") else value
    if not _RESULT.fullmatch(name) or "/" in name or "\\" in name:
        raise _blocked("--publish-subfolder must be an AI_RESULT_ basename using letters, digits, _ or -")
    return name


def _paths_overlap(first: Path, second: Path) -> bool:
    try:
        first.relative_to(second)
        return True
    except ValueError:
        try:
            second.relative_to(first)
            return True
        except ValueError:
            return False


def _check_overlap(source: Path, root: Path) -> Path:
    root = root.expanduser()
    if is_symlink_or_reparse(root):
        raise _blocked(f"work root must not be a symlink/junction/reparse point: {root}")
    root = root.resolve()
    if _paths_overlap(source, root):
        raise _blocked("work root overlaps read-only source folder")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _validate_provenance(provenance: Any, source: Path, selected: Path) -> list[dict[str, Any]]:
    if not isinstance(provenance, dict):
        raise _blocked("--publish-from must contain a provenance.json object")
    schema_version = provenance.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version != SCHEMA_VERSION:
        raise _blocked(f"provenance schema_version must be {SCHEMA_VERSION}")
    if provenance.get("folder_id") != source.name:
        raise _blocked(
            f"provenance folder_id {provenance.get('folder_id')!r} does not match input folder {source.name!r}"
        )
    rows = provenance.get("files")
    if not isinstance(rows, list) or not rows:
        raise _blocked("provenance files must be a non-empty list")
    try:
        provenance["selection_mode"] = fullset.normalize_selection_mode(provenance.get("selection_mode"))
    except fullset.ContractError as exc:
        raise _blocked(str(exc).removeprefix("blocked: ")) from exc
    gate = provenance.get("min_family_similarity_gate")
    if not isinstance(gate, (int, float)) or isinstance(gate, bool) or not math.isfinite(gate) or not fullset.MIN_FAMILY_SIMILARITY <= gate <= 1:
        raise _blocked("provenance min_family_similarity_gate must be a number")
    score = provenance.get("score")
    if not isinstance(score, dict):
        raise _blocked("provenance score must be an object with fidelity_sum, min_similarity, and average_similarity")
    for key in ("fidelity_sum", "min_similarity", "average_similarity"):
        value = score.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise _blocked(f"provenance score.{key} must be a number")
    if not gate <= score["min_similarity"] <= score["average_similarity"] <= 1 or not 0 <= score["fidelity_sum"] <= len(rows):
        raise _blocked("provenance score does not pass the family-similarity gate")
    sources, _, _ = _inventory(source)
    role_map(sources)
    expected = {unicodedata.normalize("NFC", p.stem): unicodedata.normalize("NFC", p.stem) + ".png" for p in sources}
    actual = {row.get("output_id"): row.get("filename") for row in rows if isinstance(row, dict)}
    if len(rows) != len(expected) or actual != expected:
        raise _blocked("selected provenance does not match the complete source output inventory")
    names: set[str] = set()
    verified: list[dict[str, Any]] = []
    try:
        for row in rows:
            filename, digest, output_id = row["filename"], row["selected_sha256"], row["output_id"]
            if not isinstance(filename, str) or Path(filename).name != filename or Path(filename).suffix != ".png":
                raise ValueError("filename must be a .png basename")
            if filename in names:
                raise ValueError(f"duplicate filename: {filename}")
            names.add(filename)
            path = selected / filename
            if is_symlink_or_reparse(path):
                raise _blocked(f"selected output must not be a symlink/junction/reparse point: {filename}")
            if not path.is_file() or fullset.sha256_file(path) != digest:
                raise _blocked(f"selected output missing or hash mismatch: {filename}")
            try:
                artifact = inspect_png(path)
            except ArtifactError as exc:
                raise _blocked(f"selected PNG invalid: {filename}") from exc
            if artifact["sha256"] != digest:
                raise _blocked(f"selected output changed during validation: {filename}")
            verified.append({"filename": filename, "sha256": digest, "size": path.stat().st_size, "output_id": output_id, "source_candidate_set": row.get("source_candidate_set")})
    except (KeyError, TypeError, ValueError) as exc:
        raise _blocked(f"invalid selected provenance: {exc}") from exc
    return verified



def _remove_claimed_destination(destination: Path) -> bool:
    try:
        destination.rmdir()
    except OSError:
        return False
    return not destination.exists()


def _cleanup_stage(stage: Path) -> bool:
    try:
        shutil.rmtree(stage)
    except OSError:
        return False
    return not stage.exists()


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    source = source_folder(args.input_dir)
    timestamp = args.timestamp or dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    if not _TIMESTAMP.fullmatch(timestamp):
        raise _blocked("--timestamp must match YYYYMMDD_HHMMSS")
    result_subfolder = _result_name(args.publish_subfolder, timestamp)
    if (source / result_subfolder).exists():
        raise _blocked(f"planned result subfolder already exists: {result_subfolder}; pass a fresh --timestamp")
    candidates, skipped, existing = _inventory(source)
    roles = role_map(candidates)
    by_name = {row["file"]: row for row in roles}
    folder_id = source.name
    source_hash = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:12]
    default_root = Path(tempfile.gettempdir()) / "imggen-imggen2-folder-batch" / f"{folder_id}-{source_hash}"
    work_root = _check_overlap(source, Path(args.work_root) if args.work_root else default_root)
    sources = [path.name for path in candidates]
    outputs = [{"id": unicodedata.normalize("NFC", path.stem), "filename": unicodedata.normalize("NFC", path.stem) + ".png", "prompt": _prompt(by_name[path.name])} for path in candidates]
    contract = {"schema_version": SCHEMA_VERSION, "folder_id": folder_id, "source_folder": str(source), "sources": sources, "vision_role_map": roles, "candidate_attempt_count": args.candidate_attempts, "selection_mode": fullset.normalize_selection_mode(args.selection_mode), "mpw_folder_master": FOLDER_MASTER, "qc_contract": QC_CONTRACT, "outputs": outputs}
    fullset.validate_folder_contract(contract)
    contract_path = work_root / "folder-contract.json"
    if contract_path.exists() and _canonical(fullset.read_json(contract_path)) != _canonical(contract):
        raise _blocked(f"refusing to replace a different folder contract: {contract_path}")
    if not contract_path.exists():
        fullset.atomic_json(contract_path, contract)
    source_rows = []
    for path in candidates:
        row = {"name": path.name, "sha256": fullset.sha256_file(path), "size": path.stat().st_size, **by_name[path.name]}
        row.pop("file")
        source_rows.append(row)
    handoff = {"schema_version": SCHEMA_VERSION, "folder_id": folder_id, "source_folder": str(source), "sources": source_rows, "verification_tasks": ["verify filename role mapping", "verify construction evidence", "verify occlusions", "verify product grouping"], "correction_contract": CORRECTION_CONTRACT, "qc_contract": QC_CONTRACT}
    handoff_path = work_root / "vision-handoff.json"
    plan_path = work_root / "output-plan.json"
    plan = {"schema_version": SCHEMA_VERSION, "folder_id": folder_id, "source_folder": str(source), "result_subfolder": result_subfolder, "result_path": str(source / result_subfolder), "publish_rules": {"non_overwriting": True, "originals_read_only": True, "private_artifacts_stay_outside_source": True, "source_inventory_excludes": "AI_RESULT_*"}, "outputs": [{"id": row["id"], "filename": row["filename"]} for row in outputs]}
    fullset.atomic_json(handoff_path, handoff)
    fullset.atomic_json(plan_path, plan)
    runner = None if args.dry_run else _prepare_runner(contract_path, work_root, folder_id)
    result = {"schema_version": SCHEMA_VERSION, "mode": MODE, "dry_run": bool(args.dry_run), "source_folder": str(source), "folder_id": folder_id, "work_root": str(work_root), "timestamp": timestamp, "contract_path": str(contract_path), "contract_sha256": fullset.sha256_file(contract_path), "vision_handoff_path": str(handoff_path), "output_plan_path": str(plan_path), "result_subfolder": result_subfolder, "result_path": str(source / result_subfolder), "selection_mode": contract["selection_mode"], "candidate_attempt_count": args.candidate_attempts, "counts": {"sources": len(candidates), "outputs": len(outputs), "skipped": len(skipped), "existing_result_folders": len(existing)}, "sources": [{"name": row["name"], "sha256": row["sha256"], "size": row["size"], "role": row["role"]} for row in source_rows], "skipped": skipped, "existing_result_folders": existing, "runner": runner}
    fullset.atomic_json(work_root / "prepare-summary.json", result)
    return result


def _reject_reparse_run_roots(work_root: Path, folder_id: str) -> None:
    runs_root = work_root / "runs"
    folder_root = runs_root / folder_id
    candidates = [work_root, runs_root, folder_root]
    if folder_root.is_dir() and not is_symlink_or_reparse(folder_root):
        candidates.extend(sorted(folder_root.iterdir(), key=lambda item: item.name))
    bad = sorted(str(path) for path in candidates if is_symlink_or_reparse(path))
    if bad:
        raise _blocked(f"work root contains symlink/junction/reparse entries: {bad}")


def _prepare_runner(contract_path: Path, work_root: Path, folder_id: str) -> dict[str, Any]:
    _reject_reparse_run_roots(work_root, folder_id)
    return fullset.prepare_folder(contract_path, work_root / "runs")


def _read_provenance_snapshot(provenance_path: Path) -> tuple[Any, str]:
    if not provenance_path.is_file() or is_symlink_or_reparse(provenance_path):
        raise _blocked("--publish-from must contain a non-symlink provenance.json with a files list")
    raw = provenance_path.read_bytes()
    try:
        provenance = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _blocked(f"invalid provenance JSON {provenance_path}: {exc}") from exc
    return provenance, fullset.sha256_bytes(raw)


def publish(args: argparse.Namespace) -> dict[str, Any]:
    source = source_folder(args.input_dir)
    timestamp = args.timestamp or dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    if not _TIMESTAMP.fullmatch(timestamp):
        raise _blocked("--timestamp must match YYYYMMDD_HHMMSS")
    name = _result_name(args.publish_subfolder, timestamp)
    destination = source / name
    if destination.exists():
        raise _blocked(f"result subfolder already exists: {destination}; refusing to overwrite")
    selected = _canonical_filesystem_path(args.publish_from, field="--publish-from")
    if is_symlink_or_reparse(selected):
        raise _blocked(f"--publish-from must not be a symlink/junction/reparse point: {selected}")
    if _paths_overlap(source, selected):
        raise _blocked("--publish-from overlaps read-only source folder")
    provenance, provenance_sha = _read_provenance_snapshot(selected / "provenance.json")
    verified = _validate_provenance(provenance, source, selected)
    stage: Path | None = None
    batch: dict[str, Any]
    claimed_destination = False
    try:
        stage = Path(tempfile.mkdtemp(prefix=".ai-result-stage-", dir=source))
        for row in verified:
            src, target = selected / row["filename"], stage / row["filename"]
            with src.open("rb") as inp, target.open("xb") as out:
                shutil.copyfileobj(inp, out)
            if fullset.sha256_file(target) != row["sha256"] or target.stat().st_size != row["size"]:
                raise _blocked(f"copied output verification failed: {row['filename']}")
        batch = {"schema_version": SCHEMA_VERSION, "source_folder": str(source), "result_folder": str(destination), "published": verified, "counts": {"published": len(verified), "skipped": 0, "failed": 0}, "qc_status": {"selection_mode": provenance["selection_mode"], "min_family_similarity_gate": provenance["min_family_similarity_gate"], "score": provenance["score"]}, "provenance_sha256": provenance_sha, "completed_at": timestamp}
        fullset.atomic_json(stage / "batch-summary.json", batch)
        try:
            os.chmod(stage, 0o755)
            if os.name != "nt":
                try:
                    destination.mkdir()
                    claimed_destination = True
                except FileExistsError as exc:
                    raise _blocked(f"result subfolder already exists: {destination}; refusing to overwrite") from exc
            if os.name == "nt" and destination.exists():
                raise _blocked(f"result subfolder already exists: {destination}; refusing to overwrite")
            for attempt in range(3):
                try:
                    os.rename(stage, destination)
                    stage = None
                    break
                except OSError as exc:
                    if getattr(exc, "winerror", None) in (5, 32) and attempt < 2:
                        time.sleep(0.2)
                        continue
                    raise
        except OSError as exc:
            stage_path = stage
            residue = []
            if claimed_destination and not _remove_claimed_destination(destination):
                residue.append(str(destination))
            if stage_path is not None and not _cleanup_stage(stage_path):
                residue.append(str(stage_path))
            stage = None
            if residue:
                raise _blocked(f"publish failed: {exc}; residue remains at {residue}; remove it before retrying") from exc
            raise _blocked(f"publish failed: {exc}; stage cleaned up; retry is safe") from exc
    finally:
        if stage is not None:
            shutil.rmtree(stage)
    return {"published": True, "source_folder": str(source), "result_path": str(destination), "result_subfolder": name, "counts": {"published": len(verified), "skipped": 0, "failed": 0}, "qc_status": batch["qc_status"], "batch_summary_path": str(destination / "batch-summary.json"), "files": [{"filename": row["filename"], "sha256": row["sha256"]} for row in verified]}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Prepare or publish a validated apparel product folder contract.")
    p.add_argument("--input-dir", required=True, help="Product folder containing f1/b1/fN/bN/cN/dN/sN source images.")
    p.add_argument("--mode", default=MODE, choices=[MODE])
    p.add_argument("--work-root")
    p.add_argument("--publish-subfolder", default="auto")
    p.add_argument("--timestamp")
    p.add_argument("--candidate-attempts", type=int, default=fullset.DEFAULT_CANDIDATE_ATTEMPTS)
    p.add_argument("--selection-mode", default="mixed", choices=fullset.SELECTION_MODES)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--publish-from")
    return p


def _utf8_stdout() -> None:
    # Machine-readable JSON output must stay UTF-8 even when a Windows
    # console/pipe defaults to a legacy code page that cannot encode
    # non-ASCII source names such as d1_원단.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    args = parser().parse_args(argv)
    try:
        if args.candidate_attempts < 1:
            raise _blocked("--candidate-attempts must be at least 1")
        result = publish(args) if args.publish_from else prepare(args)
    except (fullset.ContractError, PathCompatibilityError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    except OSError as exc:
        print(json.dumps({"error": f"blocked: filesystem operation failed: {exc}"}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
