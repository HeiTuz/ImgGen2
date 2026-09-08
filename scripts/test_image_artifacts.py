import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fixtures.png_fixture import png_bytes
from image_artifacts import ArtifactError, inspect_png


class ImageArtifactTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO")
    def test_nonregular_fifo_rejected_without_opening(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pipe.png"
            os.mkfifo(path)
            with patch("image_artifacts.os.open") as opened:
                with self.assertRaisesRegex(ArtifactError, "regular"):
                    inspect_png(path)
                opened.assert_not_called()

    def test_valid_pixels_metadata_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "valid.png"
            data = png_bytes(13, 17)
            path.write_bytes(data)
            self.assertEqual(inspect_png(path), {"format": "png", "width": 13, "height": 17,
                             "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})

    def test_truncated_corrupted_disguised_and_trailing_data_fail(self):
        valid = png_bytes()
        for data in (b"not a png", valid[:24], valid[:-1], valid + b"trailing",
                     valid[:29] + bytes([valid[29] ^ 1]) + valid[30:]):
            with self.subTest(length=len(data)), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "invalid.png"
                path.write_bytes(data)
                with self.assertRaises(ArtifactError):
                    inspect_png(path)

    def test_symlink_or_reparse_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unsafe.png"
            path.write_bytes(png_bytes())
            with patch("image_artifacts.is_symlink_or_reparse", return_value=True):
                with self.assertRaisesRegex(ArtifactError, "reparse"):
                    inspect_png(path)
