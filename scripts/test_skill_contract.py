import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = Path(__file__).with_name("codex_subscription_transport.py")
SPEC = importlib.util.spec_from_file_location("codex_subscription_transport_contract", MODULE_PATH)
transport = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(transport)


def skill_text():
    entry = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    manual = SKILL_ROOT / "references" / "production-workflows.md"
    if "references/production-workflows.md" not in entry:
        raise AssertionError("Detailed workflows must be reachable from the entry skill")
    return entry + "\n" + manual.read_text(encoding="utf-8")


class SkillContractTests(unittest.TestCase):
    def test_auto_vision_qc_is_risk_based_not_always_on(self):
        skill = skill_text()
        self.assertIn("`auto` is risk-based, not always-on", skill)
        self.assertIn("simple_text_only", skill)
        self.assertIn("skip Vision analysis and regeneration", skill)
        self.assertIn("at least one reference/input image exists", skill)

    @staticmethod
    def _resolved_codex():
        return SimpleNamespace(
            command="/usr/bin/codex",
            source="path",
            version=(0, 144, 3),
            provenance={"path": "/usr/bin/codex", "source": "path", "version": [0, 144, 3]},
        )

    def _references(self, root: Path, count: int) -> list[Path]:
        references = []
        for index in range(count):
            reference = root / f"reference-{index}.png"
            reference.write_bytes(b"fixture")
            references.append(reference)
        return references

    def test_generation_dry_run_resolves_output_without_calling_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(transport, "resolve_codex_command", return_value=self._resolved_codex()), \
                patch.object(transport.subprocess, "run") as run:
            root = Path(tmp)
            result = transport.run("generate a blue square", root / "result.png", [])
        run.assert_not_called()
        self.assertEqual(result["output"], str((root / "result.png").resolve()))
        self.assertEqual(result["reference_count"], 0)
        self.assertFalse(result["live"])

    def test_edit_and_two_to_four_references_are_forwarded(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            transport, "resolve_codex_command", return_value=self._resolved_codex()
        ):
            root = Path(tmp)
            for count in (1, 2, 3, 4):
                references = self._references(root, count)
                result = transport.run("edit using references", root / f"result-{count}.png", references)
                self.assertEqual(result["reference_count"], count)
                for reference in references:
                    self.assertIn(str(reference.resolve()), result["command"])

    def test_missing_reference_and_output_collision_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(transport.TransportError, "not a file"):
                transport.validate_request("edit", root / "result.png", [root / "missing.png"])
            output = root / "result.png"
            output.write_bytes(b"existing")
            with self.assertRaisesRegex(transport.TransportError, "Refusing to overwrite"):
                transport.validate_request("generate", output, [])

    def test_success_without_output_is_a_response_error(self):
        completed = transport.subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(transport, "resolve_codex_command", return_value=self._resolved_codex()), \
                patch.object(transport.subprocess, "run", return_value=completed), \
                patch.dict(transport.os.environ, {}, clear=True):
            with self.assertRaisesRegex(transport.TransportError, "did not produce"):
                transport.run("generate", Path(tmp) / "missing.png", [], execute=True)

    def test_model_label_and_file_delivery_rules_are_explicit(self):
        skill = skill_text()
        contract = (SKILL_ROOT / "references" / "execution-contract.md").read_text(encoding="utf-8")
        combined = (skill + "\n" + contract).lower()
        self.assertIn("model_identity_attested", combined)
        self.assertIn("observed_model", combined)
        self.assertIn("never turn a requested label into an attestation", combined)
        self.assertIn("file attachment", combined)
        self.assertIn("printing the path is not", combined)

    def test_prohibited_fallbacks_are_documented(self):
        text = skill_text().lower()
        for boundary in ("api-key billing", "private endpoints", "dom automation", "cookie extraction"):
            self.assertIn(boundary, text)
        self.assertIn("never fall back", text)

    def test_grok_route_is_explicit_oauth_only_and_exact_n_is_queued(self):
        skill = skill_text()
        route_path = SKILL_ROOT / "references" / "grok-oauth-explicit-routing.md"
        self.assertTrue(route_path.is_file())
        route = route_path.read_text(encoding="utf-8")
        combined = skill + route
        for required in (
            "Codex remains the default",
            "explicitly asks",
            "`Grok`, `그록`, or `xAI`",
            "`xai-oauth`",
            "native xAI `image_generate`",
            "An `XAI_API_KEY` by itself does not enable",
            "`grok_route: disabled`",
            "Never fall back",
            "exactly N independent jobs",
            "starts at 3 active jobs",
            "at most 5",
            "remaining jobs stay queued",
            "Retry only failed jobs",
        ):
            self.assertIn(required, combined)
        for forbidden_transport in (
            "`hermes chat` subprocesses",
            "start `progrok`",
            "reuse browser cookies",
            "call a private endpoint",
        ):
            self.assertIn(forbidden_transport, route)
        self.assertIn("Bare image and exact-count requests stay on Codex", combined)
        self.assertIn("API-key-only does not enable this route", route)

    def test_production_batch_contract_is_explicit(self):
        skill = skill_text()
        execution = (SKILL_ROOT / "references" / "execution-contract.md").read_text(encoding="utf-8")
        batch_contract = (SKILL_ROOT / "references" / "batch-production-contract.md").read_text(encoding="utf-8")
        batch_script = SKILL_ROOT / "scripts" / "codex_subscription_batch.py"
        combined = skill + execution + batch_contract
        self.assertTrue(batch_script.is_file())
        for required in (
            "without a second confirmation",
            "manifest_sha256",
            "approval_sha256",
            "awaiting_pilot_qc",
            "sequential transport pilot",
            "atomic ledger",
            "hash-verified",
            "retry manifest",
            "Parallel workers",
        ):
            self.assertIn(required, combined)
        self.assertIn("is still one image call", combined)

    def test_bulk_ideation_uses_mpw_without_vision_qc_or_run_residue(self):
        skill = skill_text()
        execution = (SKILL_ROOT / "references" / "execution-contract.md").read_text(encoding="utf-8")
        combined = skill + execution
        for required in (
            "creative_batch.py",
            "ideation/reference-board",
            "qc_required: false",
            "only final PNGs",
            "deleted on success",
            "retained only after failure/interruption",
        ):
            self.assertIn(required, combined)

    def test_cross_os_paths_fail_closed_with_windows_guidance(self):
        skill = skill_text()
        execution = (SKILL_ROOT / "references" / "execution-contract.md").read_text(encoding="utf-8")
        combined = skill + execution
        for required in ("/Users/...", "UNC", "WSL mount", "junction", "reparse", "errors 5 and 32"):
            self.assertIn(required, combined)

    def test_apparel_dynamic_fullset_branch_preserves_role_boundaries(self):
        skill = skill_text()
        branch_path = SKILL_ROOT / "references" / "cases" / "apparel-ghost-cut-folder-batch.md"
        self.assertTrue(branch_path.is_file())
        branch = branch_path.read_text(encoding="utf-8")
        combined = skill + branch
        for required in (
            "candidate_attempt_count",
            "color_front",
            "candidate-set-N",
            "complete source inventory",
            "80%",
            "selected/",
            "runtime-limit",
            "opaque identities",
            "Default selection is mixed",
            "selection_mode: whole-set",
            "whole-set",
            "fail closed",
            "f1",
            "b1",
            "cN",
            "dN",
            "sN",
        ):
            self.assertIn(required, combined)
        for executable in (
            SKILL_ROOT / "scripts" / "apparel_three_fullset.py",
            SKILL_ROOT / "references" / "apparel-three-fullset-folder.schema.json",
            SKILL_ROOT / "references" / "apparel-handoff.schema.json",
            SKILL_ROOT / "references" / "fixtures" / "apparel-handoff.valid.json",
        ):
            self.assertTrue(executable.is_file())
        package_version = json.loads((SKILL_ROOT / "package.json").read_text(encoding="utf-8"))["version"]
        self.assertIn(f"version: {package_version}", skill)


class OutputPathTests(unittest.TestCase):
    def test_explicit_output_wins(self):
        target = Path("/tmp/explicit-output.png")
        self.assertEqual(transport.resolve_output("blue cup", target, None), target)

    def test_single_generation_defaults_to_downloads(self):
        resolved = transport.resolve_output("A blue ceramic cup!", None, None)
        self.assertEqual(resolved.parent, transport.DOWNLOADS_DIR)
        self.assertTrue(resolved.name.startswith("a-blue-ceramic-cup-"))
        self.assertTrue(resolved.name.endswith(".png"))

    def test_single_call_batch_dir_uses_dated_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch_root = Path(tmp)
            resolved = transport.resolve_output("product shot", None, batch_root)
            self.assertEqual(resolved.parent.parent, batch_root)
            self.assertRegex(resolved.parent.name, r"^\d{8}$")
            self.assertTrue(resolved.parent.is_dir())

    def test_collisions_get_numeric_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "img.png"
            existing.write_bytes(b"x")
            self.assertEqual(transport._dedupe(existing).name, "img-2.png")

if __name__ == "__main__":
    unittest.main()
