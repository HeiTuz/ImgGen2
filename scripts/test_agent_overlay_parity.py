"""Guard host SKILL.md overlays against canonical-rule drift.

The v1.9.1 overlays had no body substitutions for either host. Host-specific
content is limited to frontmatter, the H1, and the Host integration block.
"""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOSTS = ("claude", "codex")
# Each pair is (canonical text, host replacement). Kept explicit so a future
# approved host-specific rule mapping is both applied and reviewable here.
BODY_SUBSTITUTIONS = {
    "claude": (),
    "codex": (),
}


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        raise AssertionError("SKILL.md must begin with YAML frontmatter")
    try:
        frontmatter, body = text[4:].split("---\n", 1)
    except ValueError as exc:
        raise AssertionError("SKILL.md frontmatter is not closed") from exc
    return frontmatter, body


def frontmatter_value(frontmatter: str, key: str) -> str:
    match = re.search(rf"^\s*{re.escape(key)}:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", frontmatter, re.MULTILINE)
    if match is None:
        raise AssertionError(f"frontmatter is missing {key}")
    return match.group(1)


def canonical_rule_body(text: str) -> str:
    _, body = split_frontmatter(text)
    lines = body.splitlines(keepends=True)
    heading = next((index for index, line in enumerate(lines) if line.startswith("# ")), None)
    if heading is None:
        raise AssertionError("canonical SKILL.md is missing its H1")
    remainder = lines[heading + 1 :]
    if remainder and remainder[0].strip() == "":
        remainder = remainder[1:]
    return "".join(remainder)


def overlay_rule_body(text: str) -> str:
    _, body = split_frontmatter(text)
    lines = body.splitlines(keepends=True)
    heading = next((index for index, line in enumerate(lines) if line.startswith("# ")), None)
    if heading is None:
        raise AssertionError("overlay SKILL.md is missing its H1")
    remainder = lines[heading + 1 :]
    if remainder and remainder[0].strip() == "":
        remainder = remainder[1:]
    if not remainder or not remainder[0].startswith(">"):
        raise AssertionError("overlay SKILL.md is missing its Host integration block")
    while remainder and remainder[0].startswith(">"):
        remainder = remainder[1:]
    if remainder and remainder[0].strip() == "":
        remainder = remainder[1:]
    return "".join(remainder)


def apply_substitutions(body: str, substitutions: tuple[tuple[str, str], ...]) -> str:
    for canonical_text, overlay_text in substitutions:
        body = body.replace(canonical_text, overlay_text)
    return body


@unittest.skipUnless(
    (ROOT / "agents").is_dir(),
    "SKIP: agents/ overlays absent (install artifact) — overlay parity applies to the canonical source tree only",
)
class AgentOverlayParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package_version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
        cls.canonical = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        cls.canonical_body = canonical_rule_body(cls.canonical)

    def test_frontmatter_version_matches_package(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                frontmatter, _ = split_frontmatter((ROOT / "agents" / host / "SKILL.md").read_text(encoding="utf-8"))
                self.assertEqual(frontmatter_value(frontmatter, "version"), self.package_version)

    def test_canonical_source_names_package_version(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                frontmatter, _ = split_frontmatter((ROOT / "agents" / host / "SKILL.md").read_text(encoding="utf-8"))
                source = frontmatter_value(frontmatter, "canonical_source")
                self.assertEqual(source, f"HeiTuz/ImgGen2 SKILL.md v{self.package_version}")

    def test_normalized_rule_body_matches_canonical(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                overlay = (ROOT / "agents" / host / "SKILL.md").read_text(encoding="utf-8")
                expected = apply_substitutions(self.canonical_body, BODY_SUBSTITUTIONS[host])
                self.assertEqual(overlay_rule_body(overlay), expected)

    def test_overlay_is_a_real_host_migration(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                self.assertNotEqual((ROOT / "agents" / host / "SKILL.md").read_text(encoding="utf-8"), self.canonical)

    def test_only_supported_host_overlays_ship(self) -> None:
        self.assertEqual(sorted(path.name for path in (ROOT / "agents").iterdir() if path.is_dir()), sorted(HOSTS))


if __name__ == "__main__":
    unittest.main()
