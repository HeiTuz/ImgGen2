#!/usr/bin/env python3
"""Plan and select independent apparel product-photo candidate sets.

This module is network-free.  It prepares immutable per-task contracts, builds a
generic delegation schedule bounded by the live runtime limit, and materializes a
Vision-scored selection without overwriting prior artifacts.  Default selection
is mixed: every output cut independently takes the best gate-passing candidate
across attempts; an explicit ``selection_mode: whole-set`` keeps one coherent set.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from portable_paths import is_symlink_or_reparse
from image_artifacts import ArtifactError, inspect_png

SCHEMA_VERSION = 1
MIN_FAMILY_SIMILARITY = 0.80
DEFAULT_CANDIDATE_ATTEMPTS = 3
SOURCE_IMAGE_SUFFIXES = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
DEFAULT_SELECTION_MODE = "mixed"
SELECTION_MODES = (DEFAULT_SELECTION_MODE, "whole-set")


class ContractError(RuntimeError):
    pass


def normalize_selection_mode(value: Any, field: str = "selection_mode") -> str:
    if value is None:
        return DEFAULT_SELECTION_MODE
    if not isinstance(value, str) or value not in SELECTION_MODES:
        raise ContractError(f"blocked: unknown {field} {value!r}; supported modes: {', '.join(SELECTION_MODES)}")
    return value


def _normalize_color_identity(value: Any) -> str:
    if not isinstance(value, str):
        raise ContractError("blocked: every color_front record requires an explicit non-empty color_identity")
    normalized = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
    if not normalized:
        raise ContractError("blocked: every color_front record requires an explicit non-empty color_identity")
    return normalized


def color_identities_from_role_map(role_map: list[Any]) -> list[str]:
    identities: list[str] = []
    seen: set[str] = set()
    for record in role_map:
        if not isinstance(record, dict):
            raise ContractError("vision_role_map records must be objects")
        if record.get("role") != "color_front":
            continue
        identity = _normalize_color_identity(record.get("color_identity"))
        if identity not in seen:
            identities.append(identity)
            seen.add(identity)
    if not identities:
        raise ContractError(
            "blocked: no color_front color_identity records; candidate count cannot be inferred from filenames"
        )
    return identities


def candidate_sets_for_count(task_count: int) -> tuple[str, ...]:
    if isinstance(task_count, bool) or not isinstance(task_count, int) or task_count < 1:
        raise ContractError("blocked: candidate task count must be a positive integer")
    return tuple(f"candidate-set-{index}" for index in range(1, task_count + 1))


def candidate_sets_for_shared_contract(shared: dict[str, Any]) -> tuple[str, ...]:
    attempts = shared.get("candidate_attempt_count", DEFAULT_CANDIDATE_ATTEMPTS)
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        raise ContractError("blocked: candidate_attempt_count must be a positive integer")
    return candidate_sets_for_count(attempts)


def _coordinator_candidate_sets(coordinator: dict[str, Any], shared: dict[str, Any]) -> tuple[str, ...]:
    expected_sets = candidate_sets_for_shared_contract(shared)
    task_count = coordinator.get("task_count")
    candidate_sets = coordinator.get("candidate_sets")
    task_specs = coordinator.get("task_specs")
    if task_count != len(expected_sets):
        raise ContractError("coordinator task_count does not match candidate_attempt_count")
    if candidate_sets != list(expected_sets):
        raise ContractError("coordinator candidate_sets do not match candidate_attempt_count")
    if not isinstance(task_specs, list) or len(task_specs) != task_count or not all(isinstance(p, str) for p in task_specs):
        raise ContractError("coordinator task_specs do not match its dynamic task_count")
    if coordinator.get("color_identities") != shared.get("color_identities"):
        raise ContractError("coordinator color identities do not match the shared contract")
    if coordinator.get("candidate_attempt_count") != shared.get("candidate_attempt_count"):
        raise ContractError("coordinator candidate_attempt_count does not match the shared contract")
    return expected_sets


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON {path}: {exc}") from exc


def _safe_basename(value: str, field: str) -> str:
    p = Path(value)
    if not value or p.name != value or value in {".", ".."}:
        raise ContractError(f"{field} must be one basename: {value!r}")
    return value


def validate_folder_contract(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise ContractError(f"schema_version must be {SCHEMA_VERSION}")
    folder_id = _safe_basename(str(raw.get("folder_id", "")), "folder_id")
    source_folder = Path(str(raw.get("source_folder", ""))).expanduser().resolve()
    if not source_folder.is_dir():
        raise ContractError(f"source_folder is not a directory: {source_folder}")

    source_names = raw.get("sources")
    if not isinstance(source_names, list) or not source_names:
        raise ContractError("sources must be a non-empty list containing every original image")
    sources: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for name0 in source_names:
        name = _safe_basename(str(name0), "sources[]")
        if name in seen_sources:
            raise ContractError(f"duplicate source: {name}")
        path = source_folder / name
        if not path.is_file():
            raise ContractError(f"source is not a file: {path}")
        seen_sources.add(name)
        sources.append({"name": name, "path": str(path), "sha256": sha256_file(path), "size": path.stat().st_size})
    actual_source_names = {p.name for p in source_folder.iterdir() if p.is_file() and p.suffix.lower() in SOURCE_IMAGE_SUFFIXES}
    if seen_sources != actual_source_names:
        missing = sorted(actual_source_names - seen_sources)
        extra = sorted(seen_sources - actual_source_names)
        raise ContractError(f"sources must enumerate the complete source image inventory; missing={missing}, extra={extra}")

    outputs0 = raw.get("outputs")
    if not isinstance(outputs0, list) or not outputs0:
        raise ContractError("outputs must be a non-empty complete output inventory")
    outputs: list[dict[str, str]] = []
    ids: set[str] = set()
    filenames: set[str] = set()
    for item in outputs0:
        if not isinstance(item, dict):
            raise ContractError("each output must be an object")
        output_id = _safe_basename(str(item.get("id", "")), "outputs[].id")
        filename = _safe_basename(str(item.get("filename", "")), "outputs[].filename")
        prompt = str(item.get("prompt", "")).strip()
        if not filename.lower().endswith(".png") or not prompt:
            raise ContractError(f"output {output_id} requires a .png filename and prompt")
        if output_id in ids or filename in filenames:
            raise ContractError(f"duplicate output id or filename: {output_id}/{filename}")
        ids.add(output_id)
        filenames.add(filename)
        outputs.append({"id": output_id, "filename": filename, "prompt": prompt})

    role_map = raw.get("vision_role_map")
    if not isinstance(role_map, list) or not role_map:
        role_map = []
        for name in sorted(seen_sources):
            stem = Path(name).stem.casefold()
            if stem == "f1":
                role_map.append({"file": name, "role": "color_front", "color_identity": "default"})
            elif stem == "b1":
                role_map.append({"file": name, "role": "main_back", "color_identity": "default"})
            elif stem.startswith("c") and stem[1:].isdigit():
                role_map.append({"file": name, "role": "color_front", "color_identity": stem})
            elif stem.startswith("d") and stem[1:].isdigit():
                role_map.append({"file": name, "role": "fabric_detail", "color_identity": "default"})
            elif stem.startswith("s") and stem[1:].isdigit():
                role_map.append({"file": name, "role": "composite_source", "color_identity": "default"})
        if not role_map:
            raise ContractError("vision_role_map is missing and no f1/b1/cN/dN/sN source roles were found")
    for record in role_map:
        if not isinstance(record, dict):
            raise ContractError("vision_role_map records must be objects")
        role_file = _safe_basename(str(record.get("file", "")), "vision_role_map[].file")
        if role_file not in seen_sources:
            raise ContractError(f"vision_role_map file is not in complete source inventory: {role_file}")
    color_identities = color_identities_from_role_map(role_map)
    attempts = raw.get("candidate_attempt_count", DEFAULT_CANDIDATE_ATTEMPTS)
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        raise ContractError("candidate_attempt_count must be a positive integer")
    reported_identities = raw.get("normalized_color_identity")
    if reported_identities is not None:
        if reported_identities != color_identities:
            raise ContractError("handoff normalized_color_identity does not match the Vision role map")
    reported_count = raw.get("unique_color_count")
    if reported_count is not None and reported_count != len(color_identities):
        raise ContractError("handoff unique_color_count does not match the Vision role map")
    folder_master = str(raw.get("mpw_folder_master", "")).strip()
    qc_contract = str(raw.get("qc_contract", "")).strip()
    if not folder_master or not qc_contract:
        raise ContractError("MPW folder master and QC contract are required")
    selection_mode = normalize_selection_mode(raw.get("selection_mode"))

    return {
        "schema_version": SCHEMA_VERSION,
        "folder_id": folder_id,
        "source_folder": str(source_folder),
        "sources": sources,
        "vision_role_map": role_map,
        "color_identities": color_identities,
        "candidate_attempt_count": attempts,
        "task_count": attempts,
        "selection_mode": selection_mode,
        "mpw_folder_master": folder_master,
        "qc_contract": qc_contract,
        "outputs": outputs,
        "transport": "standard-imggen2-backend",
        "selection_policy": {
            "selection_mode": selection_mode,
            "min_family_similarity": MIN_FAMILY_SIMILARITY,
            "priority": [
                "source_fidelity",
                "support_removal",
                "pure_white_no_shadow",
                "no_invented_detail",
                "family_similarity",
            ],
        },
    }


def prepare_folder(contract_path: Path, run_root: Path) -> dict[str, Any]:
    shared = validate_folder_contract(read_json(contract_path))
    candidate_sets = candidate_sets_for_shared_contract(shared)
    run_root = run_root.expanduser().resolve()
    source_folder = Path(shared["source_folder"]).resolve()
    folder_root = run_root / shared["folder_id"]
    try:
        folder_root.relative_to(source_folder)
        overlaps_source = True
    except ValueError:
        try:
            source_folder.relative_to(folder_root)
            overlaps_source = True
        except ValueError:
            overlaps_source = False
    if overlaps_source:
        raise ContractError("run root overlaps read-only source folder")
    folder_root.mkdir(parents=True, exist_ok=True)
    shared_sha = sha256_bytes(_canonical(shared))
    package_path = folder_root / "shared-folder-contract.json"
    if package_path.exists():
        existing = read_json(package_path)
        if sha256_bytes(_canonical(existing)) != shared_sha:
            raise ContractError(f"refusing to replace different shared contract: {package_path}")
    else:
        atomic_json(package_path, shared)

    task_specs = []
    for task_index, set_name in enumerate(candidate_sets, start=1):
        candidate_root = folder_root / set_name
        candidate_root.mkdir(parents=True, exist_ok=True)
        spec = {
            "schema_version": SCHEMA_VERSION,
            "task_id": f"task-{task_index}",
            "task_count": len(candidate_sets),
            "candidate_set": set_name,
            "candidate_sets": list(candidate_sets),
            "color_identities": shared["color_identities"],
            "attempt_index": task_index,
            "candidate_root": str(candidate_root),
            "shared_contract_path": str(package_path),
            "shared_contract_sha256": shared_sha,
            "source_contract_sha256": sha256_file(contract_path),
            "execution_surface": "standard ImgGen2 generation backend",
            "forbid": ["overwrite", "cross_attempt_recovery", "generated_result_chaining", "silent_provider_fallback"],
        }
        spec_path = folder_root / f"{spec['task_id']}.json"
        if spec_path.exists() and read_json(spec_path) != spec:
            raise ContractError(f"refusing to replace different task spec: {spec_path}")
        if not spec_path.exists():
            atomic_json(spec_path, spec)
        task_specs.append(str(spec_path))

    summary = {
        "folder_id": shared["folder_id"],
        "folder_root": str(folder_root),
        "shared_contract_sha256": shared_sha,
        "task_count": len(candidate_sets),
        "candidate_sets": list(candidate_sets),
        "color_identities": shared["color_identities"],
        "candidate_attempt_count": shared["candidate_attempt_count"],
        "output_inventory": [o["filename"] for o in shared["outputs"]],
        "task_specs": task_specs,
        "selector_input": str(folder_root / "vision-selector-report.json"),
        "selected_root": str(folder_root / "selected"),
    }
    coordinator_path = folder_root / "coordinator.json"
    if coordinator_path.exists():
        if read_json(coordinator_path) != summary:
            raise ContractError(f"refusing to replace different coordinator: {coordinator_path}")
    else:
        atomic_json(coordinator_path, summary)
    return summary


def inspect_candidate_task(spec_path: Path) -> dict[str, Any]:
    """Validate one prepared candidate attempt without binding it to an execution backend."""
    spec = read_json(spec_path)
    shared_path = Path(spec.get("shared_contract_path", "")).resolve()
    shared = read_json(shared_path)
    if sha256_bytes(_canonical(shared)) != spec.get("shared_contract_sha256"):
        raise ContractError("shared product specification hash mismatch")
    stored_shared = shared
    if stored_shared.get("sources") and isinstance(stored_shared["sources"][0], dict):
        shared = validate_folder_contract({
            **stored_shared,
            "sources": [source["name"] for source in stored_shared["sources"]],
        })
    else:
        shared = validate_folder_contract(stored_shared)
    if _canonical(shared) != _canonical(stored_shared):
        raise ContractError("immutable source inventory changed after preparation")
    attempts = candidate_sets_for_shared_contract(shared)
    attempt = spec.get("candidate_set")
    if attempt not in attempts:
        raise ContractError("invalid candidate attempt")
    if spec.get("candidate_sets") != list(attempts) or spec.get("task_count") != len(attempts):
        raise ContractError("task specification does not match candidate-attempt contract")
    expected_task_id = f"task-{attempts.index(attempt) + 1}"
    if spec.get("task_id") != expected_task_id:
        raise ContractError("task id does not match candidate-attempt contract")
    attempt_root = Path(spec["candidate_root"]).resolve()
    if attempt_root != shared_path.parent / attempt:
        raise ContractError("candidate root does not match disjoint attempt ownership")
    source_paths = [Path(source["path"]).resolve() for source in shared["sources"]]
    if any(not path.is_file() for path in source_paths):
        raise ContractError("complete source inventory is unavailable")
    attempt_root.mkdir(parents=True, exist_ok=True)
    return {
        "task_id": spec["task_id"],
        "candidate_set": attempt,
        "execution_surface": "standard ImgGen2 generation backend",
        "shared_contract_sha256": spec["shared_contract_sha256"],
        "source_count": len(source_paths),
        "source_inventory": [source["name"] for source in shared["sources"]],
        "complete_output_inventory": [
            {"id": output["id"], "filename": output["filename"], "path": str(attempt_root / output["filename"])}
            for output in shared["outputs"]
        ],
        "invariants": {
            "complete_source_inventory": True,
            "generated_result_chaining": False,
            "cross_attempt_recovery": False,
            "overwrite": False,
            "provider_fallback": False,
        },
    }


def _schedule_coordinator(coordinator: dict[str, Any]) -> tuple[int, list[str]]:
    task_count = coordinator.get("task_count")
    task_specs = coordinator.get("task_specs")
    candidate_sets = coordinator.get("candidate_sets")
    if isinstance(task_count, bool) or not isinstance(task_count, int) or task_count < 1:
        raise ContractError("blocked: coordinator task_count must be a positive integer")
    if candidate_sets != list(candidate_sets_for_count(task_count)):
        raise ContractError("coordinator candidate_sets do not match its dynamic task_count")
    if not isinstance(task_specs, list) or len(task_specs) != task_count or not all(isinstance(p, str) for p in task_specs):
        raise ContractError("coordinator task_specs do not match its dynamic task_count")
    return task_count, task_specs


def build_schedule(coordinators: Iterable[dict[str, Any]], max_active: int) -> list[dict[str, Any]]:
    if isinstance(max_active, bool) or not isinstance(max_active, int) or max_active < 1:
        raise ContractError("blocked: runtime limit must be a positive integer")

    waves: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_active = 0

    def emit_wave(chunk: list[dict[str, Any]]) -> None:
        generators = [
            {"kind": "generator", "folder_id": coordinator["folder_id"], "task_spec": spec}
            for coordinator in chunk
            for spec in coordinator["task_specs"]
        ]
        selectors = [
            {
                "kind": "vision-selector",
                "folder_id": coordinator["folder_id"],
                "coordinator": str(Path(coordinator["folder_root"]) / "coordinator.json"),
                "depends_on": list(coordinator["task_specs"]),
            }
            for coordinator in chunk
        ]
        waves.append({"phase": "generate", "active_count": len(generators), "tasks": generators})
        waves.append({"phase": "select", "active_count": len(selectors), "tasks": selectors})

    for coordinator in coordinators:
        task_count, _ = _schedule_coordinator(coordinator)
        if task_count > max_active:
            raise ContractError(
                f"blocked: folder {coordinator.get('folder_id', '<unknown>')} needs {task_count} generator tasks; "
                f"runtime limit is {max_active}"
            )
        if current and current_active + task_count > max_active:
            emit_wave(current)
            current = []
            current_active = 0
        current.append(coordinator)
        current_active += task_count
    if current:
        emit_wave(current)

    if any(wave["active_count"] > max_active for wave in waves):
        raise AssertionError("scheduler exceeded runtime limit")
    return waves


def _candidate_quality(entry: dict[str, Any]) -> tuple[float, bool]:
    try:
        fidelity = float(entry["source_fidelity"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("Vision candidate assessment needs numeric source_fidelity") from exc
    if not 0 <= fidelity <= 1:
        raise ContractError("source_fidelity must be in [0,1]")
    gate_values = [entry.get(k) for k in ("support_removal", "pure_white_no_shadow", "no_invented_detail")]
    if any(type(value) is not bool for value in gate_values):
        raise ContractError("Vision candidate gates must be JSON booleans")
    gates = all(gate_values)
    return fidelity, gates


def _similarity_map(report: dict[str, Any]) -> dict[tuple[str, str, str, str], float]:
    result: dict[tuple[str, str, str, str], float] = {}
    for row in report.get("similarities", []):
        try:
            key = (str(row["a_output"]), str(row["a_set"]), str(row["b_output"]), str(row["b_set"]))
            score = float(row["score"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("invalid Vision similarity row") from exc
        if not 0 <= score <= 1:
            raise ContractError("similarity score must be in [0,1]")
        if key in result:
            raise ContractError("duplicate or reversed Vision similarity pair")
        result[key] = score
        result[(key[2], key[3], key[0], key[1])] = score
    return result


def _resume_selected(selected_root: Path, outputs: list[dict[str, str]], selection_mode: str, coordinator: dict[str, Any], report_sha256: str) -> dict[str, Any] | None:
    provenance_path = selected_root / "provenance.json"
    if not selected_root.exists():
        return None
    if is_symlink_or_reparse(selected_root) or is_symlink_or_reparse(provenance_path) or not provenance_path.is_file():
        raise ContractError("selected/ exists without provenance; refusing overwrite")
    provenance = read_json(provenance_path)
    if (provenance.get("schema_version") != SCHEMA_VERSION
        or provenance.get("folder_id") != coordinator["folder_id"]
        or provenance.get("shared_contract_sha256") != coordinator["shared_contract_sha256"]
        or provenance.get("vision_report_sha256") != report_sha256):
        raise ContractError("selected resume provenance identity mismatch; refusing overwrite")
    recorded_mode = provenance.get("selection")
    if recorded_mode != selection_mode:
        raise ContractError(
            f"selected/ exists with selection mode {recorded_mode!r} but {selection_mode!r} was requested; refusing overwrite"
        )
    rows = provenance.get("files", [])
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ContractError("selected resume inventory is invalid")
    by_id = {r.get("output_id"): r for r in rows}
    if len(rows) != len(outputs) or set(by_id) != {o["id"] for o in outputs}:
        raise ContractError("selected resume inventory mismatch")
    for output in outputs:
        target = selected_root / output["filename"]
        row = by_id.get(output["id"])
        if is_symlink_or_reparse(target) or not target.is_file() or not row or row.get("filename") != output["filename"] or row.get("selected_sha256") != sha256_file(target):
            raise ContractError("selected resume verification failed; refusing overwrite")
    provenance["resume_verified"] = True
    return provenance


def _verified_candidate_outputs(
    folder_root: Path,
    coordinator: dict[str, Any],
    shared: dict[str, Any],
    candidate_sets: tuple[str, ...],
) -> dict[str, dict[str, dict[str, Any]]]:
    expected_sha = coordinator.get("shared_contract_sha256")
    if sha256_bytes(_canonical(shared)) != expected_sha:
        raise ContractError("shared folder contract does not match coordinator hash")
    expected_files = [output["filename"] for output in shared["outputs"]]
    expected_ids = {output["id"] for output in shared["outputs"]}
    verified: dict[str, dict[str, dict[str, Any]]] = {}
    for task_number, set_name in enumerate(candidate_sets, start=1):
        candidate_root = folder_root / set_name
        ledger_path = candidate_root / "task-ledger.json"
        if is_symlink_or_reparse(candidate_root) or not ledger_path.is_file() or is_symlink_or_reparse(ledger_path):
            raise ContractError(f"candidate task ledger missing for {set_name}")
        ledger = read_json(ledger_path)
        if not isinstance(ledger, dict):
            raise ContractError(f"candidate task ledger is invalid for {set_name}")
        if (
            ledger.get("schema_version") != SCHEMA_VERSION
            or ledger.get("task_id") != f"task-{task_number}"
            or ledger.get("candidate_set") != set_name
            or ledger.get("shared_contract_sha256") != expected_sha
            or ledger.get("state") != "complete"
            or ledger.get("identical_output_inventory") != expected_files
        ):
            raise ContractError(f"candidate task ledger identity is invalid for {set_name}")
        rows = ledger.get("outputs")
        if not isinstance(rows, dict) or set(rows) != expected_ids:
            raise ContractError(f"candidate task ledger inventory is incomplete for {set_name}")
        set_outputs: dict[str, dict[str, Any]] = {}
        for output in shared["outputs"]:
            row = rows.get(output["id"])
            source = candidate_root / output["filename"]
            if (
                not isinstance(row, dict)
                or row.get("state") != "completed"
                or row.get("filename") != output["filename"]
                or not isinstance(row.get("sha256"), str)
                or isinstance(row.get("size"), bool)
                or not isinstance(row.get("size"), int)
                or not source.is_file()
                or is_symlink_or_reparse(source)
                or source.stat().st_size != row["size"]
                or sha256_file(source) != row["sha256"]
            ):
                raise ContractError(f"candidate output is not ledger-verified for {set_name}/{output['id']}")
            try:
                artifact = inspect_png(source)
            except ArtifactError as exc:
                raise ContractError(f"candidate PNG invalid for {set_name}/{output['id']}: {exc}") from exc
            if artifact["sha256"] != row["sha256"] or artifact["size"] != row["size"]:
                raise ContractError("candidate changed during artifact validation")
            set_outputs[output["id"]] = {"path": source, "sha256": row["sha256"], "size": row["size"]}
        verified[set_name] = set_outputs
    return verified


def _effective_selection_mode(shared: dict[str, Any], report: dict[str, Any], cli_mode: str | None) -> str:
    contract_mode = normalize_selection_mode(shared.get("selection_mode"))
    explicit: list[str] = []
    if cli_mode is not None:
        explicit.append(normalize_selection_mode(cli_mode, "--selection-mode"))
    if report.get("selection_mode") is not None:
        explicit.append(normalize_selection_mode(report.get("selection_mode"), "report selection_mode"))
    if len(set(explicit)) > 1:
        raise ContractError("blocked: --selection-mode and the Vision report request different selection modes")
    return explicit[0] if explicit else contract_mode


def _verified_entry(
    verified_candidates: dict[str, dict[str, dict[str, Any]]],
    set_name: str,
    output: dict[str, str],
    entry: dict[str, Any],
    fidelity: float,
) -> dict[str, Any]:
    candidate = verified_candidates[set_name][output["id"]]
    return {
        "set": set_name,
        "path": candidate["path"],
        "sha256": candidate["sha256"],
        "size": candidate["size"],
        "assessment": entry,
        "fidelity": fidelity,
    }


def _family_score(
    outputs: list[dict[str, str]],
    combo: list[dict[str, Any]],
    similarities: dict[tuple[str, str, str, str], float],
) -> tuple[float, float, float]:
    """Score a chosen family; fail closed on a missing pair or a sub-threshold pair."""
    pair_scores: list[float] = []
    for i, j in itertools.combinations(range(len(outputs)), 2):
        key = (outputs[i]["id"], combo[i]["set"], outputs[j]["id"], combo[j]["set"])
        if key not in similarities:
            raise ContractError(
                f"blocked: missing family similarity for pair {outputs[i]['id']}@{combo[i]['set']} and "
                f"{outputs[j]['id']}@{combo[j]['set']}; every selected pair must be scored"
            )
        pair_scores.append(similarities[key])
    min_similarity = min(pair_scores, default=1.0)
    if min_similarity < MIN_FAMILY_SIMILARITY:
        raise ContractError("selected family does not pass the 80% family-similarity gate")
    fidelity_sum = sum(c["fidelity"] for c in combo)
    average_similarity = sum(pair_scores) / len(pair_scores) if pair_scores else 1.0
    return (fidelity_sum, min_similarity, average_similarity)


def _choose_mixed(
    outputs: list[dict[str, str]],
    candidate_sets: tuple[str, ...],
    verified_candidates: dict[str, dict[str, dict[str, Any]]],
    assessments: dict[str, Any],
    similarities: dict[tuple[str, str, str, str], float],
) -> tuple[tuple[float, float, float], list[dict[str, Any]]]:
    # Default mixed selection: every output cut independently takes the
    # highest-fidelity gate-passing candidate across attempts; fidelity ties
    # resolve deterministically to the lowest attempt index.
    combo: list[dict[str, Any]] = []
    for output in outputs:
        per_output = assessments.get(output["id"], {}).get("candidates", {})
        chosen: dict[str, Any] | None = None
        for set_name in candidate_sets:
            entry = per_output.get(set_name)
            if not isinstance(entry, dict):
                continue
            fidelity, gates = _candidate_quality(entry)
            if not gates:
                continue
            if chosen is None or fidelity > chosen["fidelity"]:
                chosen = _verified_entry(verified_candidates, set_name, output, entry, fidelity)
        if chosen is None:
            raise ContractError(f"blocked: no gate-passing candidate for output {output['id']} in any candidate set")
        combo.append(chosen)
    return _family_score(outputs, combo, similarities), combo


def _choose_whole_set(
    outputs: list[dict[str, str]],
    candidate_sets: tuple[str, ...],
    verified_candidates: dict[str, dict[str, dict[str, Any]]],
    assessments: dict[str, Any],
    similarities: dict[tuple[str, str, str, str], float],
) -> tuple[tuple[float, float, float], list[dict[str, Any]]]:
    # Explicit whole-set request: keep one complete candidate set.
    best: tuple[tuple[float, float, float], list[dict[str, Any]]] | None = None
    for set_name in candidate_sets:
        combo: list[dict[str, Any]] = []
        for output in outputs:
            entry = assessments.get(output["id"], {}).get("candidates", {}).get(set_name)
            if not isinstance(entry, dict):
                combo = []
                break
            fidelity, gates = _candidate_quality(entry)
            if not gates:
                combo = []
                break
            combo.append(_verified_entry(verified_candidates, set_name, output, entry, fidelity))
        if len(combo) != len(outputs):
            continue
        try:
            score0 = _family_score(outputs, combo, similarities)
        except ContractError:
            continue
        if best is None or score0 > best[0]:
            best = (score0, combo)
    if best is None:
        raise ContractError("no complete whole candidate set passes the 80% family-similarity gate")
    return best


def select_candidates(
    coordinator_path: Path,
    report_path: Path,
    selection_mode: str | None = None,
) -> dict[str, Any]:
    coordinator = read_json(coordinator_path)
    folder_root = Path(coordinator["folder_root"])
    shared = read_json(folder_root / "shared-folder-contract.json")
    candidate_sets = _coordinator_candidate_sets(coordinator, shared)
    outputs = shared["outputs"]
    report = read_json(report_path)
    if sha256_bytes(_canonical(shared)) != coordinator.get("shared_contract_sha256"):
        raise ContractError("shared folder contract does not match coordinator hash")
    if report.get("shared_contract_sha256") != coordinator["shared_contract_sha256"]:
        raise ContractError("Vision report is not bound to this shared folder contract")
    effective_mode = _effective_selection_mode(shared, report, selection_mode)
    selected_root = folder_root / "selected"
    resumed = _resume_selected(selected_root, outputs, effective_mode, coordinator, sha256_file(report_path))
    if resumed is not None:
        return resumed
    verified_candidates = _verified_candidate_outputs(folder_root, coordinator, shared, candidate_sets)

    if report.get("shared_contract_sha256") != coordinator["shared_contract_sha256"]:
        raise ContractError("Vision report is not bound to this shared folder contract")
    assessments = report.get("outputs")
    if not isinstance(assessments, dict):
        raise ContractError("Vision report outputs map is required")
    similarities = _similarity_map(report)

    chooser = _choose_whole_set if effective_mode == "whole-set" else _choose_mixed
    score, combo = chooser(outputs, candidate_sets, verified_candidates, assessments, similarities)
    stage = Path(tempfile.mkdtemp(prefix=".selected-stage-", dir=folder_root))
    files = []
    try:
        for output, chosen in zip(outputs, combo):
            target = stage / output["filename"]
            if chosen["path"].stat().st_size != chosen["size"] or sha256_file(chosen["path"]) != chosen["sha256"]:
                raise ContractError("candidate changed after ledger verification")
            with chosen["path"].open("rb") as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst)
            if target.stat().st_size != chosen["size"] or sha256_file(target) != chosen["sha256"]:
                raise ContractError("selected copy does not match verified candidate")
            alternatives = []
            per_output = assessments[output["id"]].get("candidates", {})
            for set_name in candidate_sets:
                if set_name == chosen["set"]:
                    continue
                alternative = per_output.get(set_name)
                available = isinstance(alternative, dict) and output["id"] in verified_candidates[set_name]
                alternatives.append({
                    "candidate_set": set_name,
                    "available": available,
                    "vision_verdict": alternative.get("vision_verdict", "") if isinstance(alternative, dict) else "",
                    "source_fidelity": alternative.get("source_fidelity") if isinstance(alternative, dict) else None,
                })
            task_number = chosen["set"].rsplit("-", 1)[-1]
            files.append({
                "output_id": output["id"],
                "filename": output["filename"],
                "source_task": f"task-{task_number}",
                "source_candidate_set": chosen["set"],
                "source_path": str(chosen["path"]),
                "source_sha256": sha256_file(chosen["path"]),
                "selected_sha256": sha256_file(target),
                "vision_verdict": chosen["assessment"].get("vision_verdict", ""),
                "source_fidelity": chosen["fidelity"],
                "rejected_alternatives": alternatives,
            })
        provenance = {
            "schema_version": SCHEMA_VERSION,
            "folder_id": coordinator["folder_id"],
            "shared_contract_sha256": coordinator["shared_contract_sha256"],
            "vision_report": str(report_path.resolve()),
            "vision_report_sha256": sha256_file(report_path),
            "selection": effective_mode,
            "selection_mode": effective_mode,
            "min_family_similarity_gate": MIN_FAMILY_SIMILARITY,
            "score": {"fidelity_sum": score[0], "min_similarity": score[1], "average_similarity": score[2]},
            "files": files,
        }
        atomic_json(stage / "provenance.json", provenance)
        try:
            stage.rename(selected_root)
        except FileExistsError as exc:
            raise ContractError("selected/ appeared during selection; refusing overwrite") from exc
        # candidate-set-* directories are disposable workspace owned by this
        # run. Originals live outside folder_root and were already proven
        # non-overlapping during prepare, so retain only the selected family.
        for set_name in candidate_sets:
            candidate_root = folder_root / set_name
            if candidate_root.exists():
                shutil.rmtree(candidate_root)
        return provenance
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--contract", type=Path, action="append", required=True)
    prep.add_argument("--run-root", type=Path, required=True)
    prep.add_argument("--runtime-limit", type=int, required=True)
    choose = sub.add_parser("select")
    choose.add_argument("--coordinator", type=Path, required=True)
    choose.add_argument("--vision-report", type=Path, required=True)
    choose.add_argument("--selection-mode", choices=list(SELECTION_MODES), default=None)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            coordinators = [prepare_folder(p.resolve(), args.run_root) for p in args.contract]
            result = {"runtime_limit": args.runtime_limit, "coordinators": coordinators, "waves": build_schedule(coordinators, args.runtime_limit)}
        else:
            result = select_candidates(args.coordinator.resolve(), args.vision_report.resolve(), args.selection_mode)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except ContractError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
