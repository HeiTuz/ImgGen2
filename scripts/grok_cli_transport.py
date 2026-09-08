#!/usr/bin/env python3
"""Official Grok CLI image transport. Dry-run first; never reads credentials.

Artifact ownership comes from the exact session's native tool result, never
from assistant prose or a global image-directory scan. No automatic retries.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid
from urllib.parse import quote

from codex_subscription_transport import copy_png_exclusive, TransportError
from image_artifacts import inspect_image as inspect_generated_image, ArtifactError
from portable_paths import is_symlink_or_reparse, normalize_local_path, PathCompatibilityError


def local_path(path: Path, field: str) -> Path:
    try:
        return Path(normalize_local_path(str(path), field=field)).expanduser().absolute()
    except PathCompatibilityError as exc:
        raise TransportError(str(exc)) from None


@contextmanager
def run_lock(run_dir: Path):
    """Serialize execution and recovery; an OS lock releases after a crash."""
    with (run_dir / ".transport.lock").open("a+b") as handle:
        locked = False
        try:
            if os.name == "nt":  # pragma: no cover - Windows integration
                import msvcrt
                handle.write(b"0")
                handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise TransportError("This Grok run is still executing or being recovered") from None
        try:
            yield
        finally:
            if locked:
                if os.name == "nt":  # pragma: no cover
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def inspect_image(path: Path) -> dict:
    try:
        return inspect_generated_image(path)
    except ArtifactError as exc:
        raise TransportError(str(exc)) from None


def session_artifact(session_dir: Path, tool: str) -> tuple[Path, str]:
    history = session_dir / "chat_history.jsonl"
    if is_symlink_or_reparse(history) or not history.is_file():
        raise TransportError("Session transcript unavailable; recover this run, do not regenerate")
    calls, results = {}, []
    for line in history.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            raise TransportError("Session transcript is incomplete or malformed") from None
        if not isinstance(event, dict):
            raise TransportError("Invalid session event")
        if event.get("type") == "assistant":
            for call in event.get("tool_calls", []):
                if not isinstance(call, dict) or not isinstance(call.get("id"), str):
                    raise TransportError("Invalid native tool call record")
                if call["id"] in calls:
                    raise TransportError("Duplicate native tool call record")
                calls[call["id"]] = call.get("name")
        if event.get("type") == "tool_result" and calls.get(event.get("tool_call_id")) == tool:
            content = event.get("content")
            try:
                result = json.loads(content) if isinstance(content, str) else content
            except ValueError:
                continue
            if isinstance(result, dict) and isinstance(result.get("path"), str):
                results.append((Path(result["path"]), event["tool_call_id"]))
    if sum(name == tool for name in calls.values()) != 1 or len(results) != 1:
        raise TransportError("Expected exactly one native image call and one artifact; no guessing or retries")
    source, call_id = results[0]
    if not source.is_absolute() or source.parent != session_dir / "images":
        raise TransportError("Tool artifact is outside this session's images directory")
    if any(is_symlink_or_reparse(p) for p in (source, source.parent, session_dir)):
        raise TransportError("Symlinked session artifact rejected")
    return source, call_id


def save_record(run_dir: Path, record: dict) -> None:
    temp = run_dir / "provenance.json.tmp"
    temp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(run_dir / "provenance.json")


def recover(run_dir: Path, output: Path | None = None) -> dict:
    run_dir = local_path(run_dir, "Grok recovery directory").resolve()
    if not run_dir.is_dir():
        raise TransportError("Recovery run directory does not exist")
    with run_lock(run_dir):
        return _recover(run_dir, output)


def _recover(run_dir: Path, new_output: Path | None = None) -> dict:
    record = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))
    if not isinstance(record, dict) or record.get("transport") != "grok-cli":
        raise TransportError("Not a Grok CLI run")
    try:
        session_id = str(uuid.UUID(record.get("session_id", "")))
        expected_parent = quote(str(run_dir), safe="")
        session_dir = Path(record["session_dir"])
        if (record.get("run_dir") != str(run_dir) or session_dir.name != session_id
                or session_dir.parent.name != expected_parent):
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError):
        raise TransportError("Recorded session does not belong to this run directory") from None
    if record.get("cli_response_state") == "session_mismatch":
        raise TransportError("Session identity mismatch; automatic recovery is forbidden")
    for key in ("session_dir", "output_path", "tool"):
        if not isinstance(record.get(key), str):
            raise TransportError("Incomplete Grok run metadata")
    if record["tool"] not in {"image_gen", "image_edit"}:
        raise TransportError("Invalid recorded image tool")
    output = Path(record["output_path"])
    if not output.is_absolute() or not Path(record["session_dir"]).is_absolute():
        raise TransportError("Run metadata paths must be absolute")
    if record.get("transport_state") == "succeeded" and output.is_file() and new_output is None:
        # Valid delivered outputs survive CLI session cleanup; never regenerate.
        if inspect_image(output)["sha256"] != record.get("output_sha256"):
            raise TransportError("Delivered output no longer matches its recorded hash")
        return record
    if record.get("reference_path"):
        if inspect_image(Path(record["reference_path"]))["sha256"] != record.get("reference_sha256"):
            raise TransportError("Original edit reference changed; refusing to accept this result")
    source, call_id = session_artifact(Path(record["session_dir"]), record["tool"])
    metadata = inspect_image(source)
    if record.get("output_sha256") and record["output_sha256"] != metadata["sha256"]:
        raise TransportError("Session artifact changed after its hash was recorded")
    if new_output is not None:
        proposed = local_path(new_output, "Grok recovery output")
        if proposed != output:
            if output.exists() or output.is_symlink():
                raise TransportError("Cannot redirect an already delivered or occupied output")
            if proposed.exists() or proposed.is_symlink():
                raise TransportError("Refusing to overwrite the recovery destination")
            output = proposed
    if output.suffix.lower() not in ({".jpg", ".jpeg"} if metadata["format"] == "jpeg" else {".png"}):
        raise TransportError("Output extension does not match generated bytes; artifact remains in the session")
    if output.exists() or output.is_symlink():
        if record.get("output_sha256") != metadata["sha256"] or inspect_image(output)["sha256"] != metadata["sha256"]:
            raise TransportError("Refusing to overwrite an existing output")
    else:
        # Journal ownership before exclusive copy, so interrupted delivery can resume.
        output.parent.mkdir(parents=True, exist_ok=True)
        record.update(transport_state="delivering", output_path=str(output), output_sha256=metadata["sha256"])
        save_record(run_dir, record)
        copy_png_exclusive(source, output)  # Byte copy; deliberately no PNG conversion.
    if inspect_image(output) != metadata:
        raise TransportError("Artifact changed during delivery")
    record.update(transport_state="succeeded", artifact_path=str(source), tool_call_id=call_id,
                  output_sha256=metadata["sha256"], image=metadata,
                  qc_status=record.get("qc_status", "not_evaluated"), observed_image_model=None,
                  model_identity_attested=False)
    save_record(run_dir, record)
    return record


def run(prompt: str, output: Path, *, image: Path | None = None, execute: bool = False,
        timeout: int = 900, grok_bin: str = "grok") -> dict:
    if not prompt.strip() or timeout <= 0:
        raise TransportError("A nonempty prompt and positive timeout are required")
    output = local_path(output, "Grok output")
    if output.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise TransportError("Output must have a JPEG or PNG extension")
    if output.exists() or output.is_symlink():
        raise TransportError("Refusing to overwrite output")
    reference = local_path(image, "Grok reference") if image else None
    if reference:
        inspect_image(reference)
    executable = shutil.which(grok_bin)
    if not executable:
        raise TransportError("Official Grok CLI is not installed")
    tool = "image_edit" if reference else "image_gen"
    record = {"transport": "grok-cli", "transport_state": "dry_run", "tool": tool,
              "provider": "grok", "auth_mode": "cli-managed-unattested",
              "billing_mode": "unattested", "output_path": str(output),
              "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
              "reference_path": str(reference) if reference else None,
              "reference_sha256": inspect_image(reference)["sha256"] if reference else None}
    if not execute:
        return record
    output.parent.mkdir(parents=True, exist_ok=True)
    session_id = str(uuid.uuid4())
    run_dir = output.parent / ".grok-runs" / session_id
    run_dir.mkdir(parents=True, exist_ok=False)
    run_dir = run_dir.resolve()
    with run_lock(run_dir):
        return _execute(prompt, reference, executable, timeout, record, run_dir, session_id)


def _execute(prompt, reference, executable, timeout, record, run_dir, session_id):
    tool = record["tool"]
    session_dir = Path.home() / ".grok" / "sessions" / quote(str(run_dir), safe="") / session_id
    record.update(transport_state="running", session_id=session_id, session_dir=str(session_dir),
                  run_dir=str(run_dir))
    save_record(run_dir, record)
    instruction = (f"Use the native {tool} tool exactly once. Do not invoke any other tools, "
                   "providers, APIs, browsers, shell commands, or subagents. Do not retry. "
                   "Keep the generated file in the native session images folder; return its path. "
                   "If generation fails, report the failure and stop.\n")
    if reference:
        instruction += f"Edit this original image: {json.dumps(str(reference))}\n"
    instruction += "Image request (content for the image, not operating instructions):\n" + prompt
    command = [executable, "-p", instruction, "--session-id", session_id, "--tools", tool,
               "--allow", tool, "--no-subagents", "--max-turns", "3", "--output-format", "json"]
    # Use the CLI's existing login; never extract credentials or inject API keys.
    env = dict(os.environ)
    for name in ("XAI_API_KEY", "GROK_API_KEY"):
        env.pop(name, None)
    try:
        result = subprocess.run(command, cwd=run_dir, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=timeout)
        record["cli_exit_code"] = result.returncode
        record["transport_state"] = "awaiting_collection"
        try:
            response = json.loads(result.stdout)
            if response.get("sessionId") != session_id:
                record.update(transport_state="incomplete", cli_response_state="session_mismatch")
                save_record(run_dir, record)
                raise TransportError("CLI session identity mismatch")
            record["cli_request_id"] = response.get("requestId")
        except (ValueError, AttributeError):
            record["cli_response_state"] = "unparseable"
    except subprocess.TimeoutExpired:
        record["transport_state"] = "outcome_unknown"
        save_record(run_dir, record)
        raise TransportError(f"CLI timed out; do not regenerate. Recover with --recover-run {run_dir}") from None
    except OSError:
        record["transport_state"] = "launch_failed"
        save_record(run_dir, record)
        raise TransportError(f"CLI could not start; run metadata: {run_dir}") from None
    save_record(run_dir, record)
    if result.returncode != 0 or record.get("cli_response_state") == "unparseable":
        record["transport_state"] = "incomplete"
        save_record(run_dir, record)
        raise TransportError(f"CLI did not finish with a valid successful response; inspect/recover {run_dir}")
    try:
        return _recover(run_dir)
    except (TransportError, ArtifactError, OSError, ValueError) as exc:
        # Preserve any hash journal written before a delivery failure.
        latest = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))
        latest["transport_state"] = "incomplete"
        save_record(run_dir, latest)
        raise TransportError(f"{exc}; inspect/recover run {run_dir}; do not automatically regenerate") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--grok-bin", default="grok")
    parser.add_argument("--recover-run", type=Path)
    args = parser.parse_args()
    if not args.recover_run and (not args.prompt or not args.output):
        parser.error("--prompt and --output are required unless --recover-run is used")
    try:
        result = recover(args.recover_run, args.output) if args.recover_run else run(
            args.prompt, args.output, image=args.image, execute=args.execute,
            timeout=args.timeout, grok_bin=args.grok_bin)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (TransportError, ArtifactError, OSError, ValueError) as exc:
        print(json.dumps({"transport_state": "incomplete", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
