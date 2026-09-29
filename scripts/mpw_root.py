"""Resolve the local MPW installation used by ImgGen2 and cross-skill tests.

MPW ships as the plugin ``mpw@heituz`` (https://github.com/HeiTuz/heituz-plugins).
``MPW_ROOT`` takes precedence when it is present in the environment and
must name a valid installation; an invalid override is an error. Without an
override, the Codex plugin cache and then the Claude Code plugin cache are
checked. A valid installation contains a ``SKILL.md`` declaring
``name: mpw`` (case-insensitive, including legacy ``MPW``). ``None`` means no
installation was found; callers that need contract authority must additionally
require its manifest.
"""

import json
import os
import re
from pathlib import Path


MARKETPLACE = "heituz"
PLUGIN = "mpw"


def _version_key(value: str):
    return [part.zfill(8) if part.isdigit() else part for part in re.split(r"[.+-]", value)]


def codex_plugin_root(codex_home: Path) -> Path | None:
    """Newest cached ``mpw@heituz`` skill under <CODEX_HOME>/plugins/cache/heituz/mpw/<version>."""
    base = codex_home / "plugins" / "cache" / MARKETPLACE / PLUGIN
    if not base.is_dir():
        return None
    versions = sorted((entry for entry in base.iterdir() if entry.is_dir()), key=lambda entry: _version_key(entry.name))
    return versions[-1] / "skills" / PLUGIN if versions else None


def claude_plugin_root(claude_home: Path) -> Path | None:
    """Active ``mpw@heituz`` skill recorded in Claude Code's installed_plugins.json."""
    registry = claude_home / "plugins" / "installed_plugins.json"
    try:
        entries = json.loads(registry.read_text(encoding="utf-8")).get("plugins", {}).get(f"{PLUGIN}@{MARKETPLACE}")
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(entries, list) or not entries:
        return None
    entry = next((item for item in entries if isinstance(item, dict) and item.get("scope") == "user"), entries[0])
    install_path = entry.get("installPath") if isinstance(entry, dict) else None
    return Path(install_path) / "skills" / PLUGIN if install_path else None


def standard_roots() -> tuple[Path, ...]:
    home = Path.home()
    codex_home = Path(os.environ["CODEX_HOME"]).expanduser() if os.environ.get("CODEX_HOME") else home / ".codex"
    return tuple(root for root in (codex_plugin_root(codex_home), claude_plugin_root(home / ".claude")) if root)


def no_installation_message() -> str:
    return (
        "SKIP: no MPW installation found "
        "(checked MPW_ROOT and the mpw@heituz plugin caches for Codex and Claude Code)"
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

    try:
        candidates = standard_roots()
    except RuntimeError:
        # No resolvable home directory (e.g. stripped env on Windows):
        # standard per-user locations cannot exist.
        return None
    for root in candidates:
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
