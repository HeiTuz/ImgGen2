"""Resolve the local MPW installation used by cross-skill tests.

``MPW_ROOT`` takes precedence when it is present in the environment and
must name a valid installation; an invalid override is an error. Without an
override, Hermes, Claude, then Codex standard locations are checked in that
order. A valid installation contains a ``SKILL.md`` declaring
``name: mpw`` (case-insensitive, including legacy ``MPW``). ``None`` means no installation was found; callers that
need contract authority must additionally require its manifest.
"""

import os
import re
from pathlib import Path


STANDARD_ROOTS = (
    Path("~/.hermes/skills/prompt-writing/MPW"),
    Path("~/.claude/skills/MPW"),
    Path("~/.codex/skills/MPW"),
)


def no_installation_message() -> str:
    return (
        "SKIP: no MPW installation found "
        "(checked MPW_ROOT and ~/.hermes/skills/prompt-writing/MPW, "
        "~/.claude/skills/MPW, ~/.codex/skills/MPW)"
    )


def is_mpw_installation(root: Path) -> bool:
    """Return whether root has the minimal MPW installation identity."""
    skill = root / "SKILL.md"
    if not root.is_dir() or not skill.is_file():
        return False
    try:
        text = skill.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return False
    frontmatter = re.match(r"\A---\n(.*?)\n---(?:\n|\Z)", text, re.DOTALL)
    if frontmatter is None:
        return False
    name_lines = [line for line in frontmatter[1].splitlines() if line.startswith("name:")]
    return len(name_lines) == 1 and bool(re.fullmatch(
        r'''name:[ \t]*(?:mpw|"mpw"|'mpw')[ \t]*(?:#.*)?''',
        name_lines[0], re.IGNORECASE,
    ))


def validate_mpw_root(root: Path, *, source: str) -> Path:
    """Return root when it is a MPW installation, otherwise raise."""
    candidate = root.expanduser()
    if not is_mpw_installation(candidate):
        raise RuntimeError(
            f"{source} is set but is not an existing MPW installation: {candidate}"
        )
    return candidate


def resolve_mpw_root() -> Path | None:
    """Return the validated override or first validated standard installation."""
    if "MPW_ROOT" in os.environ:
        override = os.environ["MPW_ROOT"]
        if not override.strip():
            raise RuntimeError("MPW_ROOT is set but is blank.")
        return validate_mpw_root(Path(override), source="MPW_ROOT")

    for candidate in STANDARD_ROOTS:
        try:
            root = candidate.expanduser()
        except RuntimeError:
            # No resolvable home directory (e.g. stripped env on Windows):
            # standard per-user locations cannot exist.
            return None
        if is_mpw_installation(root):
            return root
    return None


def require_contracts_manifest(root: Path) -> Path:
    """Return the contracts manifest or fail because the installation is incomplete."""
    manifest = root / "contracts" / "manifest.json"
    if not manifest.is_file():
        raise RuntimeError(
            f"incomplete MPW installation: contracts manifest not found: {manifest}"
        )
    return manifest
