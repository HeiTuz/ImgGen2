import hashlib
import json
from pathlib import Path
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = SKILL_ROOT / "contracts"
# Pairs of copies that must stay byte-identical (references/ is what the code reads).
APPAREL_COPIES = (
    ("references/apparel-handoff.schema.json", "contracts/v1/apparel-handoff.schema.json"),
    ("references/fixtures/apparel-handoff.valid.json", "contracts/v1/fixtures/apparel-handoff.valid.json"),
)


def text_sha256(path: Path) -> str:
    # CRLF-normalized so a Windows checkout with autocrlf hashes like the LF originals.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


class OfflineContractManifestTests(unittest.TestCase):
    """MPW-free guard: contracts/ must match the hashes pinned in contracts/manifest.json."""

    def setUp(self):
        self.manifest = json.loads((CONTRACTS / "manifest.json").read_text(encoding="utf-8"))
        self.files = self.manifest["files"]

    def test_contracts_match_manifest_hashes(self):
        self.assertTrue(self.manifest.get("contract_release"))
        for relative, expected in self.files.items():
            with self.subTest(contract=relative):
                path = CONTRACTS / relative
                self.assertTrue(path.is_file(), f"contracts/{relative} is listed in the manifest but missing")
                self.assertEqual(text_sha256(path), expected, f"contracts/{relative} differs from manifest.json")

    def test_no_unlisted_contract_files(self):
        on_disk = {
            p.relative_to(CONTRACTS).as_posix()
            for p in CONTRACTS.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        }
        self.assertEqual(on_disk - {"manifest.json"}, set(self.files))

    def test_apparel_copies_are_identical(self):
        for references_copy, contracts_copy in APPAREL_COPIES:
            with self.subTest(copy=references_copy):
                self.assertEqual(
                    text_sha256(SKILL_ROOT / references_copy),
                    text_sha256(SKILL_ROOT / contracts_copy),
                    f"{references_copy} and {contracts_copy} have diverged",
                )


if __name__ == "__main__":
    unittest.main()
