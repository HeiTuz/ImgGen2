"""Verify machine-local calibration overlays stay out of distributable artifacts."""

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(
    (ROOT / "agents").is_dir(),
    "SKIP: agents/ overlays absent (install artifact) — pack/installer exclusion applies to the canonical source tree only",
)
class LocalOverlayExclusionTests(unittest.TestCase):
    def _temporary_source(self, temporary_root: Path) -> Path:
        source = temporary_root / "source"
        shutil.copytree(
            ROOT,
            source,
            ignore=shutil.ignore_patterns(
                ".git", ".gjc", ".omx", ".codegraph", "node_modules", "__pycache__"
            ),
        )
        probe = source / "references" / "probe.local.md"
        probe.write_text("machine-local calibration\n", encoding="utf-8")
        return source

    def test_local_overlay_is_excluded_from_npm_pack_and_offline_install(self):
        npm = shutil.which("npm")
        node = shutil.which("node")
        if npm is None:
            self.skipTest("npm is required to verify npm pack exclusion")
        if node is None:
            self.skipTest("node is required to verify offline installer exclusion")

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            source = self._temporary_source(temporary_root)
            packed = subprocess.run(
                [npm, "pack", "--dry-run", "--json"],
                cwd=source,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(packed.returncode, 0, packed.stderr or packed.stdout)
            report = json.loads(packed.stdout)
            # npm <= 11 reports an array of packages; npm 12 keys the report by package name.
            package = report[0] if isinstance(report, list) else next(iter(report.values()))
            files = package["files"]
            packaged_paths = {entry["path"] for entry in files}
            self.assertIn("references/execution-contract.md", packaged_paths)
            self.assertNotIn("references/probe.local.md", packaged_paths)

            destination = temporary_root / "installed"
            installed = subprocess.run(
                [node, "scripts/install.mjs", "--offline", "--agent", "hermes", "--target", str(destination)],
                cwd=source,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr or installed.stdout)
            self.assertFalse((destination / "references" / "probe.local.md").exists())
            sentinel = destination / "references" / "full-body-calibration.local.md"
            sentinel.write_bytes(b"machine-local calibration\x00preserve me\n")
            sentinel_sha256 = hashlib.sha256(sentinel.read_bytes()).hexdigest()
            symlink_target = temporary_root / "symlink-target.local.md"
            symlink_target.write_bytes(b"do not copy symlink targets\n")
            symlink_overlay = destination / "references" / "symlink.local.md"
            try:
                symlink_overlay.symlink_to(symlink_target)
            except OSError as error:
                self.skipTest(f"symlinks are required to verify local overlay safety: {error}")

            refreshed = subprocess.run(
                [node, "scripts/install.mjs", "--offline", "--agent", "hermes", "--target", str(destination), "--force"],
                cwd=source,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(refreshed.returncode, 0, refreshed.stderr or refreshed.stdout)
            self.assertEqual(hashlib.sha256(sentinel.read_bytes()).hexdigest(), sentinel_sha256)
            self.assertFalse((destination / "references" / "probe.local.md").exists())
            self.assertFalse(symlink_overlay.exists())
            self.assertFalse(symlink_overlay.is_symlink())

    def test_canonical_skill_uses_local_overlay_contract_without_personal_defaults(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/full-body-calibration.local.md", skill)
        for prohibited in ("for this user", "180cm", "170cm"):
            self.assertNotIn(prohibited, skill)


if __name__ == "__main__":
    unittest.main()
