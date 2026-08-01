import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

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
        self.artifact.write_bytes(b"png-data")
        return {"success": True, "image": str(self.artifact), "model": kwargs["model"]}


class AlibabaTokenPlanTransportTests(unittest.TestCase):
    def test_dry_run_does_not_load_provider_or_touch_native_config(self):
        result = transport.run("beauty portrait", reference_url="https://example.com/ref.png")
        self.assertEqual(result["transport_state"], "dry_run")
        self.assertFalse(result["hermes_native_config_touched"])
        self.assertEqual(result["reference_count"], 1)
        self.assertEqual(result["input_role"], "identity_reference")

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
