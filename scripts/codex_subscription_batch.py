#!/usr/bin/env python3
"""Resumable, provenance-safe batch orchestration for ImgGen2.

Dry-run is the default. Live execution requires only --execute; the manifest and
approval digests stay in provenance to detect resume/config drift, and no
approval marker or environment ceremony is required. This module never inspects
images; QC input must come from an independent human or vision review, and that
review is execution-time safety validation — final visual QC, comparison, and
selection authority belongs to the active review workflow.
"""
from __future__ import annotations

import argparse
import contextlib
try:
    import fcntl  # POSIX
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None
    import msvcrt
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import threading
import time
from typing import Callable, Mapping, Sequence

import codex_subscription_transport as transport
from portable_paths import PathCompatibilityError, is_symlink_or_reparse, normalize_local_path


LEDGER_NAME = ".imggenimggen2-batch.json"
LOCK_NAME = ".imggenimggen2-batch.lock"
SUMMARY_JSON_NAME = "batch-summary.json"
SUMMARY_MD_NAME = "batch-summary.md"
SCHEMA_VERSION = 1
VALID_STATUSES = {"pending", "running", "succeeded", "failed", "qc_failed", "skipped"}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class BatchError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class BatchJob:
    id: str
    prompt: str
    output_path: str
    output: Path
    images: tuple[Path, ...]
    promotional: bool
    rendered_text_exists: bool
    qc_required: bool
    metadata: Mapping[str, object]
    source_record: Mapping[str, object]


def _contained(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _reject_symlink_components(root: Path, candidate: Path) -> None:
    current = root
    for part in candidate.relative_to(root).parts[:-1]:
        current = current / part
        if current.exists() and is_symlink_or_reparse(current):
            raise BatchError(f"Output parent contains a symlink, junction, or reparse point: {current}")
    if candidate.exists() and is_symlink_or_reparse(candidate):
        raise BatchError(f"Output path is a symlink, junction, or reparse point: {candidate}")


def _load_jsonl(path: Path) -> list[tuple[int, dict[str, object]]]:
    if not path.is_file():
        raise BatchError(f"JSONL file does not exist: {path}")
    rows: list[tuple[int, dict[str, object]]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BatchError(f"Invalid JSON at {path}:{line_number}: {exc.msg}") from None
        if not isinstance(value, dict):
            raise BatchError(f"JSONL record must be an object at {path}:{line_number}")
        rows.append((line_number, value))
    if not rows:
        raise BatchError(f"JSONL file has no records: {path}")
    return rows


def load_manifest(path: Path, output_root: Path) -> tuple[list[BatchJob], str]:
    path = path.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    jobs: list[BatchJob] = []
    seen_ids: set[str] = set()
    seen_outputs: set[Path] = set()
    canonical_records: list[dict[str, object]] = []
    allowed = {
        "id", "prompt", "full_prompt", "output_path", "images", "promotional",
        "rendered_text_exists", "qc_required", "metadata", "series_locks", "retry_of", "retry_generation",
        # MPW production JSONL fields retained as compile metadata.
        "category", "cut_type", "title", "format", "tier", "lane", "palette",
        "ar", "size", "quality", "output_format", "output_compression", "labels",
        "korean_copy", "status", "qa", "teaching_point", "promo_pattern",
        "look_preset", "promo_text_effect", "promo_subject", "finishing_devices",
        "palette_authority", "palette_sources",
    }
    for line_number, record in _load_jsonl(path):
        unexpected = set(record) - allowed
        if unexpected:
            raise BatchError(f"Unknown manifest fields at line {line_number}: {sorted(unexpected)}")
        job_id = record.get("id")
        prompt = record.get("prompt") or record.get("full_prompt")
        output_rel = record.get("output_path")
        if not isinstance(job_id, str) or not _ID_RE.fullmatch(job_id):
            raise BatchError(f"Invalid id at line {line_number}")
        if job_id in seen_ids:
            raise BatchError(f"Duplicate id: {job_id}")
        if not isinstance(prompt, str) or not prompt.strip():
            raise BatchError(f"Prompt must be non-empty for {job_id}")
        if not isinstance(output_rel, str) or not output_rel.strip():
            raise BatchError(f"output_path must be non-empty for {job_id}")
        rel = Path(output_rel)
        if rel.is_absolute() or ".." in rel.parts:
            raise BatchError(f"Output path must be relative and contained for {job_id}: {output_rel}")
        original_output_path = rel.as_posix()
        if rel.suffix.lower() != ".png":
            rel = rel.with_suffix(".png")
        raw_output = output_root / rel
        _reject_symlink_components(output_root, raw_output)
        output = raw_output.resolve(strict=False)
        if not _contained(output_root, output):
            raise BatchError(f"Output escapes output root for {job_id}: {output_rel}")
        if output.suffix.lower() != ".png":
            raise BatchError(f"Output normalization failed to produce PNG for {job_id}")
        if output in seen_outputs:
            raise BatchError(f"Duplicate output ownership: {output_rel}")
        raw_images = record.get("images", [])
        if not isinstance(raw_images, list) or any(not isinstance(v, str) for v in raw_images):
            raise BatchError(f"images must be a string list for {job_id}")
        if len(raw_images) > 4:
            raise BatchError(f"At most four references are supported for {job_id}")
        images: list[Path] = []
        for raw in raw_images:
            if not isinstance(raw, str) or not raw:
                raise BatchError(f"Image references must be non-empty strings for {job_id}")
            try:
                local_raw = normalize_local_path(raw, field=f"image reference for {job_id}")
            except PathCompatibilityError as exc:
                raise BatchError(str(exc)) from None
            ref_input = Path(local_raw).expanduser()
            if not ref_input.is_absolute():
                ref_input = path.parent / ref_input
            if is_symlink_or_reparse(ref_input):
                raise BatchError(f"Reference must be a non-reparse regular file for {job_id}: {raw}")
            ref = ref_input.resolve(strict=False)
            if not ref.is_file():
                raise BatchError(f"Reference must be a non-symlink regular file for {job_id}: {raw}")
            images.append(ref)
        promotional = record.get("promotional", record.get("cut_type") == "promo_poster")
        inferred_text = bool(record.get("korean_copy") or record.get("labels") or "Text-in-image:" in prompt)
        rendered = record.get("rendered_text_exists", inferred_text)
        if not isinstance(promotional, bool) or not isinstance(rendered, bool):
            raise BatchError(f"promotional/rendered_text_exists must be booleans for {job_id}")
        metadata = record.get("metadata", {})
        series_locks = record.get("series_locks", {})
        if not isinstance(metadata, dict) or not isinstance(series_locks, dict):
            raise BatchError(f"metadata/series_locks must be objects for {job_id}")
        explicit_qc = record.get("qc_required", False)
        if not isinstance(explicit_qc, bool):
            raise BatchError(f"qc_required must be a boolean for {job_id}")
        product_case = bool(
            metadata.get("product_photo") is True
            or record.get("category") in {"product", "product_photo", "product-photo"}
            or record.get("cut_type") in {"product_photo", "product_edit", "product_correction", "product_set"}
        )
        qc_required = bool(images or promotional or product_case or explicit_qc)
        merged_metadata = dict(metadata)
        reference_evidence = []
        for ref in images:
            digest, size = file_digest(ref)
            reference_evidence.append({"path": str(ref), "sha256": digest, "size": size})
        merged_metadata["reference_evidence"] = reference_evidence
        if series_locks:
            merged_metadata["series_locks"] = dict(series_locks)
        if original_output_path != rel.as_posix():
            merged_metadata["compiled_output_path"] = original_output_path
            merged_metadata["transport_output_format"] = "png"
        normalized = dict(record)
        normalized.pop("full_prompt", None)
        normalized["id"] = job_id
        normalized["prompt"] = prompt.strip()
        normalized["output_path"] = rel.as_posix()
        normalized["images"] = [str(p) for p in images]
        normalized["promotional"] = promotional
        normalized["rendered_text_exists"] = rendered
        normalized["qc_required"] = qc_required
        normalized["metadata"] = merged_metadata
        normalized.pop("series_locks", None)
        canonical_records.append(normalized)
        jobs.append(BatchJob(
            id=job_id,
            prompt=prompt.strip(),
            output_path=rel.as_posix(),
            output=output,
            images=tuple(images),
            promotional=promotional,
            rendered_text_exists=rendered,
            qc_required=qc_required,
            metadata=merged_metadata,
            source_record=normalized,
        ))
        seen_ids.add(job_id)
        seen_outputs.add(output)
    manifest_hash = _sha256_bytes(("\n".join(canonical_json(r) for r in canonical_records) + "\n").encode())
    return jobs, manifest_hash


def _initial_job_state(job: BatchJob) -> dict[str, object]:
    metadata = dict(job.metadata)
    return {
        "status": "pending",
        "output_path": job.output_path,
        "prompt_hash": _sha256_bytes(job.prompt.encode()),
        "metadata": metadata,
        "metadata_sha256": _sha256_bytes(canonical_json(metadata).encode()),
        "reference_evidence": job.metadata.get("reference_evidence", []),
        "qc_required": job.qc_required,
        "attempts": [],
        "source_artifact": None,
        "output_sha256": None,
        "output_size": None,
        "failure_category": None,
        "qc": {"status": "not_evaluated"} if job.qc_required else {"status": "skipped", "reason": "simple_text_only"},
        "updated_at": _now(),
    }


def new_ledger(jobs: Sequence[BatchJob], manifest_hash: str, config: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_sha256": manifest_hash,
        "created_at": _now(),
        "updated_at": _now(),
        "config": dict(config),
        "pilot_id": jobs[0].id,
        "awaiting_pilot_qc": False,
        "order": [job.id for job in jobs],
        "jobs": {job.id: _initial_job_state(job) for job in jobs},
    }


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp")
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with temp.open("x", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt, delay in enumerate((0.05, 0.1, 0.2, 0.4, 0.8), 1):
            try:
                os.replace(temp, path)
                break
            except OSError as exc:
                error_code = getattr(exc, "winerror", None) or exc.errno
                if os.name != "nt" or error_code not in {5, 32} or attempt == 5:
                    raise
                time.sleep(delay)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:  # directory fsync is unavailable on some platforms
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temp.unlink(missing_ok=True)


def load_ledger(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchError(f"Batch ledger is missing or corrupt: {path}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise BatchError(f"Unsupported or corrupt batch ledger: {path}")
    jobs = value.get("jobs")
    if not isinstance(jobs, dict):
        raise BatchError(f"Corrupt batch ledger jobs: {path}")
    for job_id, state in jobs.items():
        if not isinstance(state, dict) or state.get("status") not in VALID_STATUSES:
            raise BatchError(f"Corrupt batch ledger job state: {job_id}")
    return value


@contextlib.contextmanager
def batch_lock(output_root: Path):
    output_root.mkdir(parents=True, exist_ok=True)
    lock_path = output_root / LOCK_NAME
    handle = lock_path.open("a+", encoding="utf-8")
    locked = False
    try:
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:  # pragma: no cover - exercised on Windows
                handle.seek(0)
                if handle.read(1) == "":
                    handle.write("0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            locked = True
        except (BlockingIOError, OSError):
            raise BatchError(f"Another batch runner owns the output root: {output_root}") from None
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({"pid": os.getpid(), "started_at": _now()}))
        handle.flush()
        yield
    finally:
        try:
            if locked and fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif locked:  # pragma: no cover - exercised on Windows
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            handle.close()


def recover_and_validate_ledger(
    ledger: dict[str, object], jobs: Sequence[BatchJob], manifest_hash: str,
) -> None:
    if ledger.get("manifest_sha256") != manifest_hash:
        raise BatchError("Manifest drift: ledger is bound to a different canonical manifest hash.")
    if ledger.get("order") != [job.id for job in jobs]:
        raise BatchError("Manifest drift: job order or identity changed.")
    states = ledger["jobs"]
    assert isinstance(states, dict)
    for job in jobs:
        state = states.get(job.id)
        if not isinstance(state, dict):
            raise BatchError(f"Manifest drift: missing ledger job {job.id}")
        # Ledgers created before metadata provenance was added remain resumable.
        if (
            "metadata_sha256" in state
            and state["metadata_sha256"] != _sha256_bytes(canonical_json(job.metadata).encode())
        ):
            raise BatchError(f"Manifest metadata drift for job {job.id}")
        if state.get("prompt_hash") != _sha256_bytes(job.prompt.encode()) or state.get("output_path") != job.output_path:
            raise BatchError(f"Manifest drift for job {job.id}")
        if state["status"] == "running":
            state["status"] = "pending"
            state["failure_category"] = "interrupted_recovered"
            state["updated_at"] = _now()
        if state["status"] in {"succeeded", "skipped", "qc_failed"}:
            if not job.output.is_file() or is_symlink_or_reparse(job.output):
                raise BatchError(f"Resume evidence missing for {job.id}: output is absent or unsafe.")
            digest, size = file_digest(job.output)
            if digest != state.get("output_sha256") or size != state.get("output_size"):
                raise BatchError(f"Resume evidence mismatch for {job.id}: output hash/size changed.")
        elif job.output.exists():
            raise BatchError(f"Unowned existing output conflicts with job {job.id}: {job.output}")


def auto_worker_target(todo: int, hard_cap: int, ram_per_worker_gb: float) -> int:
    if todo <= 0:
        return 1
    if hard_cap < 1 or ram_per_worker_gb <= 0:
        raise BatchError("hard_cap and ram_per_worker_gb must be positive")
    cap = hard_cap
    try:
        free_bytes = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        cap = min(cap, max(1, int(free_bytes / (ram_per_worker_gb * 1_000_000_000))))
    except (ValueError, OSError, AttributeError):
        cap = min(cap, max(1, os.cpu_count() or 1))
    return max(1, min(todo, cap))


def approval_digest(
    manifest_hash: str, workers: str, start: int, hard_cap: int,
    ramp_every: int, ram_per_worker_gb: float,
) -> str:
    scope = {
        "manifest_sha256": manifest_hash,
        "workers": str(workers),
        "start": start,
        "hard_cap": hard_cap,
        "ramp_every": ramp_every,
        "ram_per_worker_gb": ram_per_worker_gb,
    }
    return _sha256_bytes(canonical_json(scope).encode())


def resolve_worker_target(todo: int, workers: str, hard_cap: int, ram_per_worker_gb: float) -> int:
    if hard_cap < 1 or ram_per_worker_gb <= 0:
        raise BatchError("hard_cap must be positive and ram_per_worker_gb must be greater than zero")
    try:
        target = auto_worker_target(todo, hard_cap, ram_per_worker_gb) if workers == "auto" else int(workers)
    except ValueError:
        raise BatchError("workers must be 'auto' or a positive integer") from None
    if target < 1 or target > hard_cap:
        raise BatchError(f"workers must be between 1 and hard_cap={hard_cap}")
    return min(todo, target)


class AdaptiveLimiter:
    def __init__(self, target: int, start: int, ramp_every: int):
        if target < 1 or start < 1 or ramp_every < 1:
            raise BatchError("worker target, start, and ramp_every must be positive")
        self.target = target
        self.ramp_every = ramp_every
        self.permits = min(start, target)
        self._semaphore = threading.Semaphore(self.permits)
        self._lock = threading.Lock()
        self._healthy = 0
        self.throttled = False

    def __enter__(self):
        self._semaphore.acquire()
        return self

    def __exit__(self, *_args):
        self._semaphore.release()

    def success(self) -> None:
        with self._lock:
            if self.throttled or self.permits >= self.target:
                return
            self._healthy += 1
            if self._healthy >= self.ramp_every:
                self._healthy = 0
                self.permits += 1
                self._semaphore.release()

    def throttle(self) -> None:
        with self._lock:
            self.throttled = True
            self._healthy = 0


def _failure_category(exc: Exception) -> str:
    text = str(exc)
    match = re.search(r"category=([a-z0-9_-]+)", text)
    if match:
        return match.group(1)
    if "timed out" in text.lower():
        return "timeout"
    if "overwrite" in text.lower() or "collision" in text.lower():
        return "output_conflict"
    return "transport_error"


def _attempt_namespace(state: Mapping[str, object]) -> int:
    attempts = state.get("attempts", [])
    return len(attempts) + 1 if isinstance(attempts, list) else 1


def _run_one(
    job: BatchJob,
    ledger: dict[str, object],
    ledger_path: Path,
    ledger_lock: threading.Lock,
    limiter: AdaptiveLimiter,
    runner: Callable[..., Mapping[str, object]],
    codex_bin: str,
    codex_provenance: Mapping[str, object],
) -> tuple[str, str]:
    states = ledger["jobs"]
    assert isinstance(states, dict)
    with limiter:
        with ledger_lock:
            state = states[job.id]
            assert isinstance(state, dict)
            attempt = _attempt_namespace(state)
            state["status"] = "running"
            state["updated_at"] = _now()
            state["attempts"].append({"attempt": attempt, "started_at": _now(), "status": "running"})
            ledger["updated_at"] = _now()
            atomic_write_json(ledger_path, ledger)
        try:
            job.output.parent.mkdir(parents=True, exist_ok=True)
            result = runner(
                job.prompt,
                job.output,
                list(job.images),
                execute=True,
                codex_bin=codex_bin,
                codex_provenance=codex_provenance,
            )
            if result.get("transport_state") != "succeeded":
                raise BatchError("Transport did not report succeeded state.")
            digest, size = file_digest(job.output)
            with ledger_lock:
                state = states[job.id]
                state["status"] = "succeeded"
                state["source_artifact"] = result.get("source_artifact")
                state["output_sha256"] = digest
                state["output_size"] = size
                state["failure_category"] = None
                state["updated_at"] = _now()
                state["attempts"][-1].update({"status": "succeeded", "finished_at": _now(), "source_artifact": result.get("source_artifact")})
                ledger["updated_at"] = _now()
                atomic_write_json(ledger_path, ledger)
            limiter.success()
            return job.id, "succeeded"
        except Exception as exc:
            category = _failure_category(exc)
            if category == "rate_limited":
                limiter.throttle()
            with ledger_lock:
                state = states[job.id]
                state["status"] = "failed"
                state["failure_category"] = category
                state["updated_at"] = _now()
                state["attempts"][-1].update({"status": "failed", "finished_at": _now(), "failure_category": category})
                ledger["updated_at"] = _now()
                atomic_write_json(ledger_path, ledger)
            return job.id, "failed"


def build_summary(ledger: Mapping[str, object]) -> dict[str, object]:
    order = ledger.get("order", [])
    states = ledger.get("jobs", {})
    items: list[dict[str, object]] = []
    counts = {status: 0 for status in VALID_STATUSES}
    awaiting_qc: list[str] = []
    for job_id in order:
        state = states[job_id]
        status = state["status"]
        counts[status] += 1
        qc_status = state.get("qc", {}).get("status", "not_evaluated")
        if state.get("qc_required") and status == "succeeded" and qc_status == "not_evaluated":
            awaiting_qc.append(job_id)
        items.append({
            "id": job_id,
            "status": status,
            "output_path": state.get("output_path"),
            "attempts": len(state.get("attempts", [])),
            "failure_category": state.get("failure_category"),
            "qc_required": bool(state.get("qc_required")),
            "qc_status": qc_status,
        })
    return {
        "manifest_sha256": ledger.get("manifest_sha256"),
        "codex_provenance": dict(
            ledger.get("config", {}).get("codex_provenance", {})
            if isinstance(ledger.get("config"), dict) else {}
        ),
        "updated_at": ledger.get("updated_at"),
        "pilot_id": ledger.get("pilot_id"),
        "awaiting_pilot_qc": bool(ledger.get("awaiting_pilot_qc")),
        "awaiting_qc": awaiting_qc,
        "counts": counts,
        "items": items,
    }


def summary_markdown(summary: Mapping[str, object]) -> str:
    provenance = summary.get("codex_provenance", {})
    lines = [
        "# ImgGen2 batch summary",
        "",
        f"Manifest: `{summary['manifest_sha256']}`",
        f"Codex: `{provenance.get('path')}` ({provenance.get('source')}, version {provenance.get('version')})",
        "",
        "| id | status | attempts | QC | output | failure |",
        "|---|---:|---:|---:|---|---|",
    ]
    for item in summary["items"]:
        lines.append(
            f"| {item['id']} | {item['status']} | {item['attempts']} | {item['qc_status']} | "
            f"`{item['output_path']}` | {item['failure_category'] or ''} |"
        )
    return "\n".join(lines) + "\n"


def write_summaries(output_root: Path, ledger: Mapping[str, object], ledger_path: Path | None = None) -> dict[str, object]:
    summary = build_summary(ledger)
    if ledger_path is None or ledger_path.name == LEDGER_NAME:
        json_path = output_root / SUMMARY_JSON_NAME
        md_path = output_root / SUMMARY_MD_NAME
    else:
        stem = ledger_path.stem.lstrip(".") or "batch"
        json_path = output_root / f"{stem}-summary.json"
        md_path = output_root / f"{stem}-summary.md"
    atomic_write_json(json_path, summary)
    temp = md_path.with_name(f".{md_path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temp.write_text(summary_markdown(summary), encoding="utf-8")
    os.replace(temp, md_path)
    return summary


def run_batch(
    manifest: Path,
    output_root: Path,
    *,
    execute: bool = False,
    workers: str = "auto",
    start: int = 1,
    hard_cap: int = 8,
    ramp_every: int = 3,
    ram_per_worker_gb: float = 0.5,
    runner: Callable[..., Mapping[str, object]] = transport.run,
    ledger_path: Path | None = None,
    codex_bin: str | Path | None = None,
) -> dict[str, object]:
    output_root = output_root.expanduser().resolve()
    jobs, manifest_hash = load_manifest(manifest, output_root)
    if start < 1 or ramp_every < 1:
        raise BatchError("start and ramp_every must be positive")
    planned_target = resolve_worker_target(len(jobs), workers, hard_cap, ram_per_worker_gb)
    try:
        resolved_codex = transport.resolve_codex_command(codex_bin)
    except transport.CodexResolutionError as exc:
        raise BatchError(str(exc)) from None
    codex_provenance = resolved_codex.provenance
    config = {
        "workers": workers, "start": start, "hard_cap": hard_cap,
        "ramp_every": ramp_every, "ram_per_worker_gb": ram_per_worker_gb,
        "codex_provenance": codex_provenance,
    }
    approval_hash = approval_digest(manifest_hash, workers, start, hard_cap, ramp_every, ram_per_worker_gb)
    config["approval_sha256"] = approval_hash
    if not execute:
        return {
            "mode": "dry_run", "live": False, "manifest_sha256": manifest_hash,
            "approval_sha256": approval_hash,
            "codex_provenance": dict(codex_provenance),
            "jobs": len(jobs), "pilot_id": jobs[0].id,
            "worker_target": planned_target,
            "worker_start": min(start, planned_target),
            "ramp_every": ramp_every,
            "hard_cap": hard_cap,
            "outputs": [job.output_path for job in jobs],
        }
    # --execute is already a bounded, explicit invocation. The manifest and
    # approval digest stay in provenance and protect resume/config drift, but
    # copying the digest into an env var is no longer required.
    output_root.mkdir(parents=True, exist_ok=True)
    ledger_path = (output_root / LEDGER_NAME) if ledger_path is None else ledger_path.expanduser().resolve()
    if not _contained(output_root, ledger_path):
        raise BatchError("Ledger path must be contained by the output root.")
    with batch_lock(output_root):
        if ledger_path.exists():
            ledger = load_ledger(ledger_path)
            recover_and_validate_ledger(ledger, jobs, manifest_hash)
            if ledger.get("config") != config:
                raise BatchError("Execution config drift: resume must use the originally approved worker bounds.")
        else:
            ledger = new_ledger(jobs, manifest_hash, config)
            recover_and_validate_ledger(ledger, jobs, manifest_hash)
            atomic_write_json(ledger_path, ledger)
        states = ledger["jobs"]
        assert isinstance(states, dict)
        pilot_id = str(ledger.get("pilot_id") or jobs[0].id)
        pilot = next((job for job in jobs if job.id == pilot_id), jobs[0])
        pilot_state = states[pilot.id]
        pending = [job for job in jobs if states[job.id]["status"] == "pending"]
        unresolved = [job.id for job in jobs if states[job.id]["status"] in {"failed", "qc_failed"}]
        if pending and unresolved:
            raise BatchError(
                "Batch has unresolved failures; create a retry manifest and run it with a separate ledger before continuing."
            )
        ledger_lock = threading.Lock()
        try:
            if pilot_state["status"] == "pending":
                _, pilot_status = _run_one(
                    pilot,
                    ledger,
                    ledger_path,
                    ledger_lock,
                    AdaptiveLimiter(1, 1, 1),
                    runner,
                    resolved_codex.command,
                    codex_provenance,
                )
                if pilot_status != "succeeded":
                    ledger["pilot_failed"] = True
                    ledger["awaiting_pilot_qc"] = False
                    ledger["updated_at"] = _now()
                    atomic_write_json(ledger_path, ledger)
                    summary = write_summaries(output_root, ledger, ledger_path)
                    summary["pilot_failed"] = True
                    return summary
                if pilot.qc_required:
                    ledger["awaiting_pilot_qc"] = True
                    ledger["updated_at"] = _now()
                    atomic_write_json(ledger_path, ledger)
                    return write_summaries(output_root, ledger, ledger_path)

            pilot_qc = pilot_state.get("qc", {})
            pilot_qc_passed = isinstance(pilot_qc, dict) and pilot_qc.get("status") == "passed"
            if pilot.qc_required and pilot_state["status"] == "succeeded" and not pilot_qc_passed:
                ledger["awaiting_pilot_qc"] = True
                ledger["updated_at"] = _now()
                atomic_write_json(ledger_path, ledger)
                return write_summaries(output_root, ledger, ledger_path)
            if pilot_state["status"] in {"failed", "qc_failed"}:
                return write_summaries(output_root, ledger, ledger_path)

            ledger["awaiting_pilot_qc"] = False
            ledger["updated_at"] = _now()
            atomic_write_json(ledger_path, ledger)
            pending = [job for job in jobs if states[job.id]["status"] == "pending"]
            if not pending:
                return write_summaries(output_root, ledger, ledger_path)
            target = resolve_worker_target(len(pending), workers, hard_cap, ram_per_worker_gb)
            limiter = AdaptiveLimiter(target, start, ramp_every)
            with ThreadPoolExecutor(max_workers=target) as pool:
                futures = [
                    pool.submit(
                        _run_one,
                        job,
                        ledger,
                        ledger_path,
                        ledger_lock,
                        limiter,
                        runner,
                        resolved_codex.command,
                        codex_provenance,
                    )
                    for job in pending
                ]
                for future in as_completed(futures):
                    future.result()
        finally:
            pass
        return write_summaries(output_root, ledger, ledger_path)


def _qc_record_map(path: Path) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for line, record in _load_jsonl(path.expanduser().resolve()):
        job_id = record.get("id")
        if not isinstance(job_id, str) or job_id in records:
            raise BatchError(f"QC records require unique string id at line {line}")
        records[job_id] = record
    return records


def reconcile_qc(
    manifest: Path, output_root: Path, qc_results: Path, retry_manifest: Path | None = None,
    ledger_path: Path | None = None,
) -> dict[str, object]:
    output_root = output_root.expanduser().resolve()
    jobs, manifest_hash = load_manifest(manifest, output_root)
    ledger_path = (output_root / LEDGER_NAME) if ledger_path is None else ledger_path.expanduser().resolve()
    if not _contained(output_root, ledger_path):
        raise BatchError("Ledger path must be contained by the output root.")
    with batch_lock(output_root):
        ledger = load_ledger(ledger_path)
        recover_and_validate_ledger(ledger, jobs, manifest_hash)
        records = _qc_record_map(qc_results)
        states = ledger["jobs"]
        assert isinstance(states, dict)
        known = {job.id for job in jobs}
        unknown = set(records) - known
        if unknown:
            raise BatchError(f"QC records reference unknown jobs: {sorted(unknown)}")
        for job in jobs:
            if job.id not in records:
                continue
            state = states[job.id]
            if state["status"] not in {"succeeded", "qc_failed", "skipped"}:
                raise BatchError(f"Cannot apply QC to non-succeeded job {job.id}")
            record = records[job.id]
            scores = record.get("axis_scores")
            rendered = record.get("rendered_text_exists", job.rendered_text_exists)
            if not isinstance(scores, dict):
                raise BatchError(f"QC axis_scores must be an object for {job.id}")
            try:
                report = transport.evaluate_qc(scores, rendered_text_exists=rendered)
            except ValueError as exc:
                raise BatchError(f"Invalid QC for {job.id}: {exc}") from None
            promo_report = None
            if job.promotional:
                promo = record.get("promo")
                if not isinstance(promo, dict):
                    raise BatchError(f"Promotional job {job.id} requires promo QC")
                try:
                    promo_report = transport.evaluate_promo_qc(**promo)
                except (TypeError, ValueError) as exc:
                    raise BatchError(f"Invalid promo QC for {job.id}: {exc}") from None
            plan = transport.plan_qc_regeneration(
                job.output, report, promo_report, promotional=job.promotional
            )
            failed = bool(plan["regenerate_outputs"])
            state["status"] = "qc_failed" if failed else "succeeded"
            state["qc"] = {"status": "failed" if failed else "passed", "report": report, "promo_report": promo_report, "regeneration_plan": plan}
            state["updated_at"] = _now()
        pilot_id = str(ledger.get("pilot_id") or jobs[0].id)
        pilot_state = states[pilot_id]
        pilot_qc = pilot_state.get("qc", {})
        if isinstance(pilot_qc, dict) and pilot_qc.get("status") == "passed":
            ledger["awaiting_pilot_qc"] = False
        elif pilot_state.get("status") == "qc_failed":
            ledger["awaiting_pilot_qc"] = False
            ledger["pilot_failed"] = True
        ledger["updated_at"] = _now()
        atomic_write_json(ledger_path, ledger)
        if retry_manifest is not None:
            write_retry_manifest(jobs, ledger, retry_manifest)
        return write_summaries(output_root, ledger, ledger_path)


def write_retry_manifest(jobs: Sequence[BatchJob], ledger: Mapping[str, object], path: Path) -> int:
    states = ledger["jobs"]
    lines: list[str] = []
    statuses = [state["status"] for state in states.values()]
    include_pending = any(status in {"failed", "qc_failed"} for status in statuses) and "pending" in statuses
    retry_statuses = {"failed", "qc_failed", "pending"} if include_pending else {"failed", "qc_failed"}
    for job in jobs:
        state = states[job.id]
        if state["status"] not in retry_statuses:
            continue
        record = dict(job.source_record)
        generation = int(record.get("retry_generation", 0)) + 1
        record["retry_generation"] = generation
        if state["status"] == "qc_failed":
            qc = state.get("qc", {})
            plan = qc.get("regeneration_plan", {}) if isinstance(qc, dict) else {}
            deltas = list((plan.get("deltas") or {}).values())
            promo_failed = plan.get("failed_promo_checks") or []
            additions = []
            if deltas:
                additions.append("Retry deltas: " + " ".join(str(v) for v in deltas))
            if promo_failed:
                additions.append("Promo corrections: " + ", ".join(str(v) for v in promo_failed) + ".")
            record["prompt"] = job.prompt + ("\n" + " ".join(additions) if additions else "")
            record["output_path"] = (Path("retries") / f"{job.id}-attempt-{generation + 1}.png").as_posix()
        record["retry_of"] = job.id
        lines.append(canonical_json(record))
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    os.replace(temp, path)
    return len(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--workers", default="auto", help="auto or positive integer")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--hard-cap", type=int, default=8)
    parser.add_argument("--ramp-every", type=int, default=3)
    parser.add_argument("--ram-per-worker-gb", type=float, default=0.5)
    parser.add_argument("--codex-bin", type=Path, help="Explicit official Codex CLI executable")
    parser.add_argument("--qc-results", type=Path)
    parser.add_argument("--retry-manifest", type=Path)
    parser.add_argument("--ledger", type=Path, help="Ledger path contained by output root; use a new ledger for retry manifests")
    args = parser.parse_args(argv)
    try:
        if args.workers != "auto":
            int(args.workers)
        if args.qc_results:
            summary = reconcile_qc(args.manifest, args.output_root, args.qc_results, args.retry_manifest, args.ledger)
        else:
            summary = run_batch(
                args.manifest, args.output_root, execute=args.execute, workers=args.workers,
                start=args.start, hard_cap=args.hard_cap, ramp_every=args.ramp_every,
                ram_per_worker_gb=args.ram_per_worker_gb, ledger_path=args.ledger,
                codex_bin=args.codex_bin,
            )
            if args.retry_manifest and args.execute:
                jobs, _ = load_manifest(args.manifest, args.output_root)
                ledger_path = (args.output_root / LEDGER_NAME) if args.ledger is None else args.ledger
                ledger = load_ledger(ledger_path.expanduser().resolve())
                write_retry_manifest(jobs, ledger, args.retry_manifest)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    except (BatchError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=os.sys.stderr)
        return 2
    counts = summary.get("counts", {}) if isinstance(summary, dict) else {}
    return 1 if any(counts.get(status, 0) for status in ("failed", "qc_failed")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
