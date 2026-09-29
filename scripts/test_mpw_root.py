import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mpw_root


class MpwRootTests(unittest.TestCase):
    def test_current_lowercase_and_legacy_names_are_supported(self):
        for name in ("mpw", "MPW", '"mpw"', "'MPW'", "mpw # canonical name"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "SKILL.md").write_text(f"---\nname: {name}\n---\n")
                self.assertTrue(mpw_root.is_mpw_installation(root))

    def test_body_mentions_and_other_skill_names_do_not_qualify(self):
        invalid = (
            "---\nname: other\n---\nExample: name: MPW\n",
            "---\nname: MPW-other\n---\n",
            "---\nmetadata:\n  name: MPW\n---\n",
            "---\nname: mpw\nname: other\n---\n",
            "name: MPW\n",
        )
        for text in invalid:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "SKILL.md").write_text(text)
                self.assertFalse(mpw_root.is_mpw_installation(root))

    def make_install(self, root: Path) -> Path:
        root.mkdir()
        (root / "SKILL.md").write_text("---\nname: MPW\n---\n", encoding="utf-8")
        return root

    def test_blank_override_raises(self):
        with mock.patch.dict(os.environ, {"MPW_ROOT": "  "}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "blank"):
                mpw_root.resolve_mpw_root()

    def test_nonexistent_override_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            with mock.patch.dict(os.environ, {"MPW_ROOT": str(missing)}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "not an existing MPW installation"):
                    mpw_root.resolve_mpw_root()

    def test_existing_non_mpw_override_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"MPW_ROOT": tmp}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "not an existing MPW installation"):
                    mpw_root.resolve_mpw_root()

    def test_standard_resolution_prefers_newest_codex_plugin_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            base = home / ".codex" / "plugins" / "cache" / "heituz" / "mpw"
            for version in ("2.9.0", "3.0.0", "3.0.0+codex.local-1"):
                self.make_install_tree(base / version / "skills" / "mpw")
            claude = self.make_claude_plugin(home, "3.1.0")
            with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}, clear=True):
                self.assertEqual(mpw_root.resolve_mpw_root(), base / "3.0.0+codex.local-1" / "skills" / "mpw")
            with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home), "CODEX_HOME": str(home / "other")}, clear=True):
                self.assertEqual(mpw_root.resolve_mpw_root(), claude)

    def test_legacy_skill_installs_are_not_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            for legacy in (home / ".hermes" / "skills" / "prompt-writing" / "MPW", home / ".claude" / "skills" / "MPW", home / ".codex" / "skills" / "MPW"):
                self.make_install_tree(legacy)
            with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}, clear=True):
                self.assertIsNone(mpw_root.resolve_mpw_root())

    def make_install_tree(self, root: Path) -> Path:
        root.mkdir(parents=True)
        (root / "SKILL.md").write_text("---\nname: mpw\n---\n", encoding="utf-8")
        return root

    def make_claude_plugin(self, home: Path, version: str) -> Path:
        install = home / ".claude" / "plugins" / "cache" / "heituz" / "mpw" / version
        skill = self.make_install_tree(install / "skills" / "mpw")
        registry = home / ".claude" / "plugins" / "installed_plugins.json"
        registry.write_text(json.dumps({"version": 2, "plugins": {"mpw@heituz": [{"scope": "user", "installPath": str(install), "version": version}]}}), encoding="utf-8")
        return skill

    def test_empty_environment_and_home_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"HOME": tmp, "USERPROFILE": tmp}, clear=True):
                self.assertIsNone(mpw_root.resolve_mpw_root())

    def test_found_install_without_manifest_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_install(Path(tmp) / "MPW")
            with mock.patch.dict(os.environ, {"MPW_ROOT": str(root)}, clear=True):
                resolved = mpw_root.resolve_mpw_root()
            with self.assertRaisesRegex(RuntimeError, "incomplete MPW installation"):
                mpw_root.require_contracts_manifest(resolved)


if __name__ == "__main__":
    unittest.main()
