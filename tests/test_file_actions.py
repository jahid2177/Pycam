import os
import tempfile
import unittest
from pathlib import Path

from storage.share import file_action_info, guess_mime_type


class FileActionTests(unittest.TestCase):
    def test_export_mime_types_are_stable(self):
        expected = {
            "a.pdf": "application/pdf",
            "a.docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "a.xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "a.csv": "text/csv",
            "a.txt": "text/plain",
            "a.jpg": "image/jpeg",
            "a.png": "image/png",
            "a.zip": "application/zip",
        }
        for name, mime in expected.items():
            self.assertEqual(guess_mime_type(name), mime)

    def test_file_action_validation_rejects_missing_and_empty(self):
        with self.assertRaises(ValueError):
            file_action_info("")
        with self.assertRaises(FileNotFoundError):
            file_action_info("/definitely/not/a/pycam/file.pdf")
        with tempfile.TemporaryDirectory() as tmp:
            empty = os.path.join(tmp, "empty.pdf")
            Path(empty).write_bytes(b"")
            with self.assertRaises(RuntimeError):
                file_action_info(empty)

    def test_file_action_metadata_for_real_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "Result.PDF")
            Path(path).write_bytes(b"%PDF-1.4\n%%EOF\n")
            info = file_action_info(path)
            self.assertEqual(info["path"], os.path.abspath(path))
            self.assertEqual(info["name"], "Result.PDF")
            self.assertGreater(info["size"], 0)
            self.assertEqual(info["mime"], "application/pdf")

    def test_android_bridge_does_not_expose_raw_file_uri(self):
        source = Path(__file__).resolve().parents[1] / "storage" / "share.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("copy_to_shared", text)
        self.assertIn("view_file", text)
        self.assertIn("share_file", text)
        self.assertNotIn("Uri.fromFile", text)
        self.assertNotIn('Uri.parse("file://', text)

    def test_export_surfaces_have_open_and_share_actions(self):
        root = Path(__file__).resolve().parents[1]
        for rel in ("ui/home.py", "ui/documents.py"):
            text = (root / rel).read_text(encoding="utf-8")
            self.assertIn('text="OPEN"', text)
            self.assertIn('text="SHARE"', text)
            self.assertIn("_open_exported", text)
        advanced = (root / "ui/advanced_tools.py").read_text(encoding="utf-8")
        self.assertIn("OPEN RESULT", advanced)
        self.assertIn("SHARE RESULT", advanced)
        self.assertIn("def open_result", advanced)
        ocr = (root / "ui/ocr_result.py").read_text(encoding="utf-8")
        self.assertIn("OPEN EXPORT", ocr)
        self.assertIn("SHARE EXPORT", ocr)
        self.assertIn("def open_export", ocr)
        self.assertIn("def share_export", ocr)


if __name__ == "__main__":
    unittest.main()
