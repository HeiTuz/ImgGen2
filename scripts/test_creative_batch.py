from fixtures.png_fixture import png_bytes
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import creative_batch
import mpw_prompt_adapter


def write_manifest(_prompt, _style, count, output, **_kwargs):
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for index in range(1, count + 1):
            handle.write(json.dumps({
                "id": f"variation-{index:03d}",
                "full_prompt": f"enhanced variation {index}",
                "output_path": f"images/{index:03d}.png",
                "qc_required": False,
                "metadata": {"mpw_compiled": True, "ideation_batch": count > 1},
            }) + "\n")
    return output


class MpwPromptAdapterTests(unittest.TestCase):
    def test_invalid_mpw_root_is_reported_as_a_prompt_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(mpw_prompt_adapter.MpwPromptError, "not an existing MPW installation"):
                mpw_prompt_adapter.discover_mpw_root(Path(tmp))

    def test_failed_compile_preserves_existing_output_and_removes_temps(self):
        for outcome in ("exit", "truncated", "timeout", "replace"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output = root / "existing.jsonl"
                output.write_bytes(b"original manifest")
                def compiler(command, **kwargs):
                    path = Path(command[command.index("--output") + 1])
                    if outcome == "timeout":
                        raise mpw_prompt_adapter.subprocess.TimeoutExpired(command, 120)
                    path.write_text('{"full_prompt":"valid"}\n' if outcome == "replace" else '{broken')
                    return mock.Mock(returncode=1 if outcome == "exit" else 0)
                with mock.patch.object(mpw_prompt_adapter, "discover_mpw_root", return_value=root), \
                     mock.patch.object(mpw_prompt_adapter.subprocess, "run", side_effect=compiler):
                    if outcome == "replace":
                        with mock.patch.object(Path, "replace", side_effect=OSError("locked")):
                            with self.assertRaises(mpw_prompt_adapter.MpwPromptError):
                                mpw_prompt_adapter.compile_manifest("cat", "", 1, output)
                    else:
                        with self.assertRaises(mpw_prompt_adapter.MpwPromptError):
                            mpw_prompt_adapter.compile_manifest("cat", "", 1, output)
                self.assertEqual(output.read_bytes(), b"original manifest")
                self.assertEqual(list(root.iterdir()), [output])

    def test_single_prompt_modes(self):
        self.assertEqual(mpw_prompt_adapter.compile_single_prompt("plain", mode="off"), ("plain", False))
        with mock.patch.object(mpw_prompt_adapter, "discover_mpw_root", return_value=None):
            self.assertEqual(mpw_prompt_adapter.compile_single_prompt("plain", mode="auto"), ("plain", False))
            with self.assertRaises(mpw_prompt_adapter.MpwPromptError):
                mpw_prompt_adapter.compile_single_prompt("plain", mode="required")

    def test_auto_hook_compiles_one_and_cleans_temp(self):
        with mock.patch.object(mpw_prompt_adapter, "discover_mpw_root", return_value=Path("/fake/mpw")), \
             mock.patch.object(mpw_prompt_adapter, "compile_manifest", side_effect=write_manifest):
            prompt, compiled = mpw_prompt_adapter.compile_single_prompt("plain", mode="auto")
        self.assertTrue(compiled)
        self.assertEqual(prompt, "enhanced variation 1")


class CreativeBatchTests(unittest.TestCase):
    def test_final_output_conflict_is_rejected_before_any_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp) / "final"
            final.mkdir()
            (final / "existing.png").write_bytes(b"original deliverable")
            runner = mock.Mock()
            with mock.patch.object(creative_batch, "compile_manifest") as compiler:
                with self.assertRaisesRegex(creative_batch.CreativeBatchError, "not empty"):
                    creative_batch.run_creative_batch("cats", "", 2, final, execute=True, batch_runner=runner)
                compiler.assert_not_called()
                runner.assert_not_called()
            self.assertEqual((final / "existing.png").read_bytes(), b"original deliverable")
            self.assertEqual(list(Path(tmp).iterdir()), [final])

    def test_dry_run_preserves_failed_run_on_success_and_error(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as tmp:
                final = Path(tmp) / "final"
                workspace = creative_batch._workspace_for(final, "cats", "", 2, None)
                workspace.mkdir()
                write_manifest("cats", "", 2, workspace / "variations.jsonl")
                (workspace / "generated").mkdir()
                (workspace / "generated" / "001.png").write_bytes(b"verified prior image")
                (workspace / "generated" / "ledger.json").write_text('{"status":"failed"}')
                before = {p.relative_to(workspace): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
                planned = []

                def runner(manifest, output_root, **kwargs):
                    planned.append(manifest.parent)
                    self.assertNotEqual(manifest.parent, workspace)
                    self.assertEqual(manifest.read_bytes(), before[Path("variations.jsonl")])
                    self.assertFalse(kwargs["execute"])
                    if fail:
                        raise creative_batch.batch.BatchError("preflight failure")
                    return {"mode": "dry_run", "jobs": 2}

                with mock.patch.object(creative_batch, "compile_manifest") as compiler:
                    if fail:
                        with self.assertRaisesRegex(creative_batch.CreativeBatchError, "resume state was preserved"):
                            creative_batch.run_creative_batch("cats", "", 2, final, batch_runner=runner)
                    else:
                        result = creative_batch.run_creative_batch("cats", "", 2, final, batch_runner=runner)
                        self.assertTrue(result["workspace_retained"])
                    compiler.assert_not_called()
                after = {p.relative_to(workspace): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
                self.assertEqual(before, after)
                self.assertTrue(planned)
                self.assertTrue(all(not path.exists() for path in planned))

    def test_failed_new_dry_run_cleans_only_its_scratch(self):
        paths = []

        def failing_compile(_prompt, _style, _count, output, **_kwargs):
            paths.append(output.parent)
            output.write_text("partial compile")
            raise creative_batch.MpwPromptError("compiler failure")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            creative_batch, "compile_manifest", side_effect=failing_compile,
        ):
            with self.assertRaisesRegex(creative_batch.CreativeBatchError, "Dry-run failed"):
                creative_batch.run_creative_batch("cats", "", 2, Path(tmp) / "final")
            self.assertEqual(list(Path(tmp).iterdir()), [])
            self.assertTrue(all(not path.exists() for path in paths))

    def test_hundred_item_dry_run_is_qc_free_and_leaves_no_workspace(self):
        captured = {}
        def dry_runner(manifest, output_root, **kwargs):
            rows = [json.loads(line) for line in Path(manifest).read_text().splitlines()]
            captured["rows"] = rows
            return {"mode": "dry_run", "jobs": len(rows), "outputs": [row["output_path"] for row in rows]}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(creative_batch, "compile_manifest", side_effect=write_manifest):
            final = Path(tmp) / "final"
            result = creative_batch.run_creative_batch("cats", "indie editorial", 100, final, batch_runner=dry_runner)
            self.assertFalse(final.exists())
            self.assertFalse(any(Path(tmp).glob(".final.imggen-work-*")))
        self.assertEqual(len(captured["rows"]), 100)
        self.assertEqual(len({row["full_prompt"] for row in captured["rows"]}), 100)
        self.assertTrue(all(row["qc_required"] is False for row in captured["rows"]))
        self.assertFalse(result["workspace_retained"])

    def test_success_publishes_only_images_and_removes_workspace(self):
        def success_runner(manifest, output_root, **kwargs):
            from test_codex_subscription_batch import FakeRunner
            from unittest.mock import patch
            from types import SimpleNamespace
            resolved = SimpleNamespace(command="/test/codex", provenance={"path": "/test/codex"})
            with patch.object(creative_batch.batch.transport, "resolve_codex_command", return_value=resolved):
                result = creative_batch.batch.run_batch(manifest, output_root, execute=True, runner=FakeRunner())
            # Unrelated output must never become a delivered image.
            (Path(output_root) / "unowned.png").write_bytes(png_bytes(seed=99))
            return result
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(creative_batch, "compile_manifest", side_effect=write_manifest):
            final = Path(tmp) / "final"
            result = creative_batch.run_creative_batch("cats", "indie editorial", 3, final, execute=True, batch_runner=success_runner)
            self.assertEqual(sorted(path.name for path in final.iterdir()), ["001.png", "002.png", "003.png"])
            self.assertTrue(all(path.is_file() for path in final.iterdir()))
            self.assertFalse(any(Path(tmp).glob(".final.imggen-work-*")))
            self.assertEqual(result["count"], 3)

    def test_failure_retains_workspace_for_resume(self):
        def failed_runner(_manifest, _output_root, **_kwargs):
            return {"counts": {"succeeded": 1, "failed": 1}, "awaiting_qc": [], "awaiting_pilot_qc": False}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(creative_batch, "compile_manifest", side_effect=write_manifest):
            final = Path(tmp) / "final"
            with self.assertRaisesRegex(creative_batch.CreativeBatchError, "workspace retained"):
                creative_batch.run_creative_batch("cats", "", 2, final, execute=True, batch_runner=failed_runner)
            workspaces = list(Path(tmp).glob(".final.imggen-work-*"))
            self.assertEqual(len(workspaces), 1)
            self.assertTrue((workspaces[0] / "variations.jsonl").is_file())
            self.assertFalse(final.exists())


if __name__ == "__main__":
    unittest.main()
