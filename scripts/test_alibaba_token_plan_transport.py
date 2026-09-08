import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from fixtures.png_fixture import png_bytes

MODULE_PATH = Path(__file__).resolve().parent / "alibaba_token_plan_transport.py"
SPEC = importlib.util.spec_from_file_location("alibaba_token_plan_transport", MODULE_PATH)
transport = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(transport)


class FakeProvider:
    def __init__(self, artifact: Path):
        self.artifact = artifact
        self.calls = []

    def generate(self, prompt, aspect_ratio, **kwargs):
        self.calls.append((prompt, aspect_ratio, kwargs))
        self.artifact.write_bytes(png_bytes(seed=len(self.calls)))
        return {"success": True, "image": str(self.artifact), "model": kwargs["model"]}


class AlibabaTokenPlanTransportTests(unittest.TestCase):
    def test_dry_run_does_not_load_provider_or_touch_native_config(self):
        result = transport.run("beauty portrait", reference_url="https://example.com/ref.png")
        self.assertEqual(result["transport_state"], "dry_run")
        self.assertFalse(result["hermes_native_config_touched"])
        self.assertEqual(result["reference_count"], 1)
        self.assertEqual(result["input_role"], "identity_reference")

    def test_same_prompt_repeated_runs_have_distinct_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); provider=FakeProvider(root/"cache.png")
            first=transport.run("portrait",execute=True,run_root=root/"runs",provider=provider)
            second=transport.run("portrait",execute=True,run_root=root/"runs",provider=provider)
            self.assertNotEqual(first["run_id"],second["run_id"])
            self.assertTrue(Path(first["provenance_path"]).is_file())
            self.assertTrue(Path(second["provenance_path"]).is_file())
            self.assertNotEqual(first["artifact_path"], second["artifact_path"])
            first_bytes = Path(first["artifact_path"]).read_bytes()
            provider.artifact.unlink()
            self.assertEqual(Path(first["artifact_path"]).read_bytes(), first_bytes)
            self.assertEqual(transport._sha256(Path(first["artifact_path"])), first["artifact_sha256"])

    def test_invalid_provider_image_is_not_accepted(self):
        class Invalid(FakeProvider):
            def generate(self, *args, **kwargs):
                self.artifact.write_bytes(b'not an image')
                return {"success": True, "image": str(self.artifact)}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(transport.TransportError, "invalid or unstable"):
                transport.run("cup", execute=True, run_root=root / 'runs', provider=Invalid(root / 'cache.png'))

    def test_provider_error_does_not_expose_raw_diagnostics(self):
        class Broken:
            def generate(self,*args,**kwargs): raise RuntimeError("secret sentinel")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(transport.TransportError) as caught:
                transport.run("portrait",execute=True,run_root=Path(tmp),provider=Broken())
            self.assertNotIn("secret sentinel",str(caught.exception))

    def test_rejects_local_reference(self):
        with self.assertRaisesRegex(transport.TransportError, "public HTTP"):
            transport.run("portrait", reference_url="/tmp/ref.png")

    def test_execute_writes_imggen2_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = FakeProvider(root / "cache.png")
            result = transport.run("portrait", reference_url="https://example.com/ref.png", execute=True, run_root=root / "runs", provider=provider)
            provenance = json.loads(Path(result["provenance_path"]).read_text())
        self.assertEqual(result["transport_state"], "succeeded")
        self.assertEqual(provenance["transport"], "imggen2-alibaba-token-plan")
        self.assertEqual(provenance["provider"], "alibaba-token-plan")
        self.assertEqual(provenance["qc_status"], "pending_review")
        self.assertFalse(provenance["hermes_native_config_touched"])
        self.assertEqual(provider.calls[0][2]["model"], "wan2.7-image")
        self.assertNotIn("image_url", provider.calls[0][2])
        self.assertEqual(provider.calls[0][2]["reference_image_urls"], ["https://example.com/ref.png"])
        self.assertEqual(provenance["reference_summary"]["input_role"], "identity_reference")
        self.assertIsNone(provenance["reference_summary"]["regeneration_parent_artifact_id"])


if __name__ == "__main__":
    unittest.main()
