from pathlib import Path
import os
import tempfile
import zipfile
import unittest

from database.database import DocumentDatabase
from storage.preferences import AppPreferences
from storage.manager import StorageManager


class CoreRegressionTests(unittest.TestCase):
    def test_preferences_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefs = AppPreferences(tmp)
            prefs.set("edge_sensitivity", "high")
            self.assertEqual(AppPreferences(tmp).get("edge_sensitivity"), "high")

    def test_database_create_search_and_favorite(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = DocumentDatabase(os.path.join(tmp, "docs.db"))
            doc_id = db.create_document(
                "Invoice September",
                os.path.join(tmp, "page.jpg"),
                ocr_text="Total payable 1250 taka",
                pages=[os.path.join(tmp, "page.jpg")],
            )
            self.assertEqual(len(db.list_documents(search="1250")), 1)
            db.set_favorite(doc_id, True)
            self.assertEqual(len(db.list_documents(favorites_only=True)), 1)

    def test_export_filename_is_safe_and_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = StorageManager.__new__(StorageManager)
            storage.root = tmp
            storage._ensure_dirs()
            first = storage.get_export_path("../bad:name?.pdf")
            self.assertEqual(os.path.dirname(first), os.path.join(tmp, storage.EXPORTS_DIR))
            self.assertNotIn("..", os.path.basename(first))
            open(first, "wb").close()
            second = storage.get_export_path("../bad:name?.pdf")
            self.assertNotEqual(first, second)




class BuildConfigurationTests(unittest.TestCase):
    def test_bengali_ocr_build_configuration(self):
        from pathlib import Path
        project = Path(__file__).resolve().parents[1]
        spec = (project / "buildozer.spec").read_text(encoding="utf-8")
        self.assertIn("traineddata", spec)
        self.assertIn("com.rmtheis:tess-two:9.1.0", spec)
        workflow = (project / ".github" / "workflows" / "build-apk.yml").read_text(encoding="utf-8")
        self.assertIn("tessdata_fast/4.1.0/${LANG}.traineddata", workflow)
        self.assertIn("test -s assets/tessdata/ben.traineddata", workflow)




class MixedOcrBuildTests(unittest.TestCase):
    def test_mixed_ocr_is_registered(self):
        root = Path(__file__).resolve().parents[1]
        manager = (root / "ocr" / "ocr_manager.py").read_text(encoding="utf-8")
        self.assertIn('"mixed": MixedRecognizer', manager)
        self.assertIn('in {"bengali", "mixed"}', manager)

    def test_build_downloads_both_tessdata_models(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "build-apk.yml").read_text(encoding="utf-8")
        self.assertIn('for LANG in eng ben', workflow)
        self.assertIn('assets/tessdata/${LANG}.traineddata', workflow)
        self.assertIn('test -s assets/tessdata/eng.traineddata', workflow)
        self.assertIn('test -s assets/tessdata/ben.traineddata', workflow)



class PassportPhotoAlignmentTests(unittest.TestCase):
    def test_eye_rotation_helper_levels_pair(self):
        import numpy as np
        from image_processing.passport_photo import _rotate_from_eye_pair
        image = np.full((240, 200, 3), 220, np.uint8)
        aligned, angle = _rotate_from_eye_pair(image, [(60.0, 90.0), (140.0, 102.0)])
        self.assertEqual(aligned.shape, image.shape)
        self.assertGreater(abs(angle), 1.0)
        self.assertLess(abs(angle), 18.0)

    def test_passport_output_sizes_without_face(self):
        import numpy as np
        from image_processing.passport_photo import create_passport_photo
        image = np.full((900, 700, 3), 180, np.uint8)
        bd, bd_mm = create_passport_photo(image, preset="bangladesh", background="white", dpi=300)
        us, us_mm = create_passport_photo(image, preset="usa", background="white", dpi=300)
        self.assertEqual(bd_mm, (35.0, 45.0))
        self.assertEqual(us_mm, (51.0, 51.0))
        self.assertEqual((bd.shape[1], bd.shape[0]), (413, 531))
        self.assertEqual((us.shape[1], us.shape[0]), (602, 602))


    def test_app_version_metadata(self):
        from storage.app_version import APP_VERSION, APP_SCHEMA_VERSION
        self.assertEqual(APP_VERSION, "1.1.0")
        self.assertGreaterEqual(APP_SCHEMA_VERSION, 3)

if __name__ == "__main__":
    unittest.main()


class TableOcrHelpersTest(unittest.TestCase):
    def test_parse_and_export_table(self):
        from tools.table_ocr import parse_text_table, table_to_tsv, tsv_to_rows
        from tools.document_tools import create_csv_from_rows, create_xlsx_from_rows
        import tempfile
        rows = parse_text_table("Name  Qty  Price\nPen   2    10\nBook  1    50")
        self.assertEqual(rows[0], ["Name", "Qty", "Price"])
        self.assertEqual(tsv_to_rows(table_to_tsv(rows)), rows)
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "table.csv")
            xlsx_path = os.path.join(d, "table.xlsx")
            create_csv_from_rows(rows, csv_path)
            create_xlsx_from_rows(rows, xlsx_path)
            self.assertTrue(os.path.getsize(csv_path) > 20)
            self.assertTrue(zipfile.is_zipfile(xlsx_path))

    def test_grid_detection(self):
        from tools.table_ocr import detect_table_grid, crop_grid_cells
        import tempfile
        import cv2, numpy as np
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "grid.png")
            img = np.full((360, 600, 3), 255, np.uint8)
            for x in (30, 210, 390, 570):
                cv2.line(img, (x, 30), (x, 330), (0,0,0), 3)
            for y in (30, 130, 230, 330):
                cv2.line(img, (30, y), (570, y), (0,0,0), 3)
            cv2.imwrite(path, img)
            xs, ys = detect_table_grid(path)
            self.assertGreaterEqual(len(xs), 4)
            self.assertGreaterEqual(len(ys), 4)
            cells = crop_grid_cells(path)
            self.assertGreaterEqual(len(cells), 3)
            self.assertGreaterEqual(len(cells[0]), 3)


class AdvancedPdfToolsTests(unittest.TestCase):
    def _make_pdf(self, path, pages=3, metadata=None):
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(path)
        for i in range(pages):
            c.drawString(72, 720, f"Page {i + 1}")
            c.showPage()
        c.save()
        if metadata:
            from pypdf import PdfReader, PdfWriter
            r = PdfReader(path)
            w = PdfWriter()
            for p in r.pages:
                w.add_page(p)
            w.add_metadata(metadata)
            with open(path, 'wb') as f:
                w.write(f)

    def test_advanced_pdf_page_operations(self):
        from pypdf import PdfReader
        from tools.document_tools import (
            remove_pdf_pages, insert_pdf_pages, add_page_numbers,
            add_header_footer, edit_pdf_metadata, flatten_pdf,
        )
        with tempfile.TemporaryDirectory() as d:
            base = os.path.join(d, 'base.pdf')
            extra = os.path.join(d, 'extra.pdf')
            self._make_pdf(base, 3)
            self._make_pdf(extra, 2)

            removed = remove_pdf_pages(base, os.path.join(d, 'removed.pdf'), '2')
            self.assertEqual(len(PdfReader(removed).pages), 2)

            inserted = insert_pdf_pages(base, extra, os.path.join(d, 'inserted.pdf'), 1)
            self.assertEqual(len(PdfReader(inserted).pages), 5)

            numbered = add_page_numbers(base, os.path.join(d, 'numbered.pdf'), 5)
            self.assertEqual(len(PdfReader(numbered).pages), 3)

            headed = add_header_footer(base, os.path.join(d, 'hf.pdf'), 'HEADER', 'FOOTER')
            self.assertEqual(len(PdfReader(headed).pages), 3)

            meta = edit_pdf_metadata(base, os.path.join(d, 'meta.pdf'), 'Title=Scan\nAuthor=Pycam')
            reader = PdfReader(meta)
            self.assertEqual(reader.metadata.title, 'Scan')
            self.assertEqual(reader.metadata.author, 'Pycam')

            flat = flatten_pdf(base, os.path.join(d, 'flat.pdf'))
            self.assertEqual(len(PdfReader(flat).pages), 3)

    def test_pdf_unlock(self):
        from pypdf import PdfReader, PdfWriter
        from tools.document_tools import unlock_pdf
        with tempfile.TemporaryDirectory() as d:
            plain = os.path.join(d, 'plain.pdf')
            locked = os.path.join(d, 'locked.pdf')
            unlocked = os.path.join(d, 'unlocked.pdf')
            self._make_pdf(plain, 1)
            r = PdfReader(plain)
            w = PdfWriter()
            for p in r.pages:
                w.add_page(p)
            w.encrypt('1234')
            with open(locked, 'wb') as f:
                w.write(f)
            unlock_pdf(locked, unlocked, '1234')
            self.assertFalse(PdfReader(unlocked).is_encrypted)


class LongImageExportTests(unittest.TestCase):
    def test_single_and_segmented_long_image(self):
        from PIL import Image
        from tools.document_tools import combine_images_vertically
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for i in range(6):
                path = os.path.join(d, f"p{i}.jpg")
                Image.new("RGB", (600, 1500), (245 - i * 10, 245, 245)).save(path, "JPEG")
                paths.append(path)

            single = combine_images_vertically(
                paths[:2], os.path.join(d, "single.jpg"),
                max_width=600, max_segment_height=4000, gap_px=4,
            )
            self.assertTrue(single.endswith(".jpg"))
            self.assertTrue(os.path.isfile(single))
            with Image.open(single) as im:
                self.assertEqual(im.width, 600)
                self.assertEqual(im.height, 3004)

            segmented = combine_images_vertically(
                paths, os.path.join(d, "long.jpg"),
                max_width=600, max_segment_height=6000, gap_px=4,
            )
            self.assertTrue(segmented.endswith(".zip"))
            self.assertTrue(os.path.isfile(segmented))
            with zipfile.ZipFile(segmented) as z:
                names = sorted(z.namelist())
                self.assertEqual(len(names), 2)
                self.assertEqual(names[0], "long_image_001.jpg")

class TestBiometricConfiguration(unittest.TestCase):
    def test_biometric_defaults_and_permission(self):
        from storage.preferences import DEFAULTS
        self.assertFalse(DEFAULTS.get("biometric_unlock"))
        spec = Path("buildozer.spec").read_text(encoding="utf-8")
        self.assertIn("USE_BIOMETRIC", spec)

    def test_pin_clear_disables_biometric(self):
        from storage.security import clear_pin
        class P:
            def __init__(self): self.v = {"biometric_unlock": True, "app_lock_enabled": True}
            def set(self, k, v): self.v[k] = v
        p = P()
        clear_pin(p)
        self.assertFalse(p.v["biometric_unlock"])
        self.assertFalse(p.v["app_lock_enabled"])

    def test_app_lock_keeps_pin_fallback(self):
        source = Path("ui/app_lock.py").read_text(encoding="utf-8")
        self.assertIn('text="BIOMETRIC"', source)
        self.assertIn('text="UNLOCK"', source)
        self.assertIn("verify_pin", source)
        self.assertIn("authenticate", source)


class ExportDestinationTests(unittest.TestCase):
    def test_export_destination_defaults_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefs = AppPreferences(tmp)
            self.assertEqual(prefs.get("export_destination"), "app")
            self.assertEqual(prefs.get("export_tree_uri"), "")
            self.assertEqual(prefs.get("app_language"), "en")
            prefs.set("export_destination", "custom")
            prefs.set("export_tree_uri", "content://example/tree/primary%3ADocuments")
            self.assertEqual(AppPreferences(tmp).get("export_destination"), "custom")
            self.assertTrue(AppPreferences(tmp).get("export_tree_uri").startswith("content://"))

    def test_custom_folder_duplicate_name_generation(self):
        from storage.export_destination import _unique_display_name
        existing = {"Scan.pdf", "Scan_2.pdf", "Scan_3.pdf"}
        self.assertEqual(_unique_display_name("Scan.pdf", existing), "Scan_4.pdf")
        self.assertEqual(_unique_display_name("Fresh.pdf", existing), "Fresh.pdf")


class BuildPackagingHardeningTests(unittest.TestCase):
    def test_buildozer_packages_only_arm64(self):
        root = Path(__file__).resolve().parents[1]
        spec = (root / "buildozer.spec").read_text(encoding="utf-8")
        self.assertIn("android.archs = arm64-v8a", spec)
        self.assertNotIn("x86_64", spec)
        self.assertNotIn("armeabi-v7a", spec)

    def test_development_files_are_excluded(self):
        root = Path(__file__).resolve().parents[1]
        spec = (root / "buildozer.spec").read_text(encoding="utf-8")
        exclude_line = next(line for line in spec.splitlines() if line.startswith("source.exclude_dirs"))
        for name in ("tests", "build-debug", "release", ".pytest_cache"):
            self.assertIn(name, exclude_line)
        patterns = next(line for line in spec.splitlines() if line.startswith("source.exclude_patterns"))
        self.assertIn("*.zip", patterns)
        self.assertIn("*.apk", patterns)

    def test_permissions_are_trimmed(self):
        root = Path(__file__).resolve().parents[1]
        spec = (root / "buildozer.spec").read_text(encoding="utf-8")
        permissions = next(line for line in spec.splitlines() if line.startswith("android.permissions"))
        self.assertIn("CAMERA", permissions)
        self.assertIn("READ_MEDIA_IMAGES", permissions)
        self.assertIn("POST_NOTIFICATIONS", permissions)
        self.assertIn("USE_BIOMETRIC", permissions)
        self.assertIn("READ_EXTERNAL_STORAGE;maxSdkVersion=32", permissions)
        self.assertNotIn("READ_MEDIA_VIDEO", permissions)
        self.assertNotIn("WRITE_EXTERNAL_STORAGE", permissions)
        self.assertNotIn("MANAGE_EXTERNAL_STORAGE", permissions)

    def test_workflow_audits_apk_size_and_abi(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "build-apk.yml").read_text(encoding="utf-8")
        self.assertIn("Audit APK contents", workflow)
        self.assertIn("apk-largest-files.txt", workflow)
        self.assertIn("apk-abis.txt", workflow)
        self.assertIn("larger than 180 MB", workflow)

class Android16CompatibilityTests(unittest.TestCase):
    def test_static_android_compatibility_audit(self):
        from storage.android_compat import static_android_compatibility_audit
        root = Path(__file__).resolve().parents[1]
        report = static_android_compatibility_audit(root)
        self.assertTrue(report["ok"], report["issues"])
        self.assertGreaterEqual(report["checks_passed"], 10)

    def test_notifications_do_not_create_pending_intent(self):
        from storage.android_compat import _python_identifiers
        root = Path(__file__).resolve().parents[1]
        names = _python_identifiers(root / "storage" / "notifications.py")
        self.assertNotIn("PendingIntent", names)

    def test_checked_intent_launchers_are_wired(self):
        root = Path(__file__).resolve().parents[1]
        actions = (root / "storage" / "android_actions.py").read_text(encoding="utf-8")
        export = (root / "storage" / "export_destination.py").read_text(encoding="utf-8")
        self.assertIn("start_activity_checked", actions)
        self.assertIn("start_activity_for_result_checked", export)


class HealthCheckTests(unittest.TestCase):
    def test_database_integrity_check(self):
        from database.database import DocumentDatabase
        with tempfile.TemporaryDirectory() as tmp:
            db = DocumentDatabase(os.path.join(tmp, "documents.db"))
            db.initialize()
            status = db.integrity_check()
            self.assertTrue(status["ok"])
            self.assertEqual(status["quick_check"].lower(), "ok")
            self.assertEqual(status["missing_columns"], [])

    def test_health_report_is_persisted_and_non_destructive(self):
        from database.database import DocumentDatabase
        from storage.health_check import run_health_check, read_last_health_report

        class Storage:
            def __init__(self, root): self.root = root
        class Prefs:
            def __init__(self): self.values = {"export_destination": "app", "export_tree_uri": ""}
            def get(self, key): return self.values.get(key)
            def set(self, key, value): self.values[key] = value
        class App: pass

        with tempfile.TemporaryDirectory() as tmp:
            app = App()
            app.storage = Storage(tmp)
            app.prefs = Prefs()
            app.db = DocumentDatabase(os.path.join(tmp, "documents.db"))
            app.db.initialize()
            report = run_health_check(app, tmp, deep=False, persist=True)
            self.assertIn("checks", report)
            names = {item["name"] for item in report["checks"]}
            self.assertIn("storage", names)
            self.assertIn("database", names)
            self.assertIn("tessdata:eng", names)
            saved = read_last_health_report(app)
            self.assertEqual(saved["profile"], "quick")
            self.assertGreaterEqual(len(saved["checks"]), 5)

class ToolRouteAuditTests(unittest.TestCase):
    def test_all_visible_tools_have_real_routes(self):
        from storage.health_check import _tool_route_check
        root = Path(__file__).resolve().parents[1]
        result = _tool_route_check(root)
        self.assertEqual(result["status"], "ok", result["message"])
        self.assertGreaterEqual(result.get("visible_tools", 0), 30)
        self.assertGreaterEqual(result.get("lazy_screens", 0), 30)

    def test_no_placeholder_markers_in_user_facing_tool_routes(self):
        root = Path(__file__).resolve().parents[1]
        sources = [
            root / "ui" / "tools.py",
            root / "ui" / "advanced_tools.py",
            root / "ui" / "tool_workflows.py",
            root / "ui" / "print_tool.py",
            root / "ui" / "ai_chat.py",
        ]
        forbidden = ("not connected", "coming soon", "workflow connected নয়", "placeholder feature")
        text = "\n".join(p.read_text(encoding="utf-8").lower() for p in sources if p.is_file())
        for marker in forbidden:
            self.assertNotIn(marker.lower(), text)

class FreehandAnnotationTests(unittest.TestCase):
    def test_freehand_pen_erase_restore_pipeline(self):
        import tempfile
        from pathlib import Path
        import cv2
        import numpy as np
        from image_processing.annotations import apply_freehand_strokes

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "page.jpg"
            base = np.full((240, 320, 3), 245, dtype=np.uint8)
            cv2.line(base, (20, 120), (300, 120), (80, 80, 80), 2)
            self.assertTrue(cv2.imwrite(str(path), base))
            strokes = [
                {"mode": "pen", "brush": 0.018, "points": [(0.15, 0.25), (0.85, 0.25)]},
                {"mode": "highlight", "brush": 0.04, "points": [(0.2, 0.55), (0.8, 0.55)]},
                {"mode": "erase", "brush": 0.025, "points": [(0.45, 0.75), (0.55, 0.75)]},
                {"mode": "restore", "brush": 0.03, "points": [(0.48, 0.25), (0.52, 0.25)]},
            ]
            apply_freehand_strokes(str(path), strokes)
            out = cv2.imread(str(path))
            self.assertIsNotNone(out)
            self.assertEqual(out.shape, base.shape)
            self.assertFalse(np.array_equal(out, base))

class SessionAutosaveRecoveryTests(unittest.TestCase):
    def test_draft_metadata_tracks_reason_and_timestamp(self):
        import json
        from storage.manager import StorageManager
        with tempfile.TemporaryDirectory() as tmp:
            manager = StorageManager.__new__(StorageManager)
            manager.app_name = "PycamTest"
            manager.root = tmp
            manager._ensure_dirs()
            page = os.path.join(tmp, "source.jpg")
            with open(page, "wb") as fh:
                fh.write(b"page-data")
            copied = manager.save_session_draft([page], editing_document_id=7, reason="crop")
            self.assertEqual(len(copied), 1)
            meta_path = os.path.join(tmp, manager.DRAFTS_DIR, "draft.json")
            with open(meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            self.assertEqual(meta["editing_document_id"], 7)
            self.assertEqual(meta["reason"], "crop")
            self.assertTrue(meta["updated_at"].endswith("+00:00"))

    def test_edit_surfaces_schedule_recovery_autosave(self):
        root = Path(__file__).resolve().parents[1]
        expected = {
            "ui/editor.py": ("editor_reorder", "editor_delete", "editor_rotate"),
            "ui/preview.py": ("preview_undo", "freehand_annotation", "fine_adjustment", "filter_commit"),
            "ui/crop.py": ("manual_crop",),
        }
        for rel, markers in expected.items():
            text = (root / rel).read_text(encoding="utf-8")
            for marker in markers:
                self.assertIn(marker, text, f"{marker} missing from {rel}")

    def test_protected_document_plaintext_is_not_draft_autosaved(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "main.py").read_text(encoding="utf-8")
        self.assertIn('doc.get("protected")', text)
        self.assertIn('autosave_skipped:protected_document', text)
        self.assertIn('schedule_session_autosave', text)

class IDPassportIntelligenceTests(unittest.TestCase):
    def test_nid_structured_fields(self):
        from tools.id_passport_intelligence import parse_bangladesh_nid_text
        text = """Government of the People's Republic of Bangladesh
Name: MD JAHIDUL ISLAM
পিতা: ABDUL KARIM
মাতা: RAHIMA BEGUM
Date of Birth: 15 Jan 1995
NID No: 1234 567 890
Blood Group: O+
"""
        data = parse_bangladesh_nid_text(text)
        self.assertEqual(data["name_english"], "MD JAHIDUL ISLAM")
        self.assertEqual(data["nid_number"], "1234567890")
        self.assertEqual(data["blood_group"], "O+")
        self.assertIn("1995", data["date_of_birth"])

    def test_td3_passport_mrz_validation(self):
        from tools.id_passport_intelligence import parse_passport_mrz
        # ICAO Doc 9303 commonly used TD3 example.
        text = (
            "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
            "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
        )
        data = parse_passport_mrz(text)
        self.assertTrue(data["valid_mrz"])
        self.assertEqual(data["passport_number"], "L898902C3")
        self.assertEqual(data["surname"], "ERIKSSON")
        self.assertEqual(data["given_names"], "ANNA MARIA")
        self.assertEqual(data["date_of_birth"], "1974-08-12")
        self.assertEqual(data["expiry_date"], "2012-04-15")

    def test_td3_detects_bad_checksum(self):
        from tools.id_passport_intelligence import parse_passport_mrz
        text = (
            "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
            "L898902C30UTO7408122F1204159ZE184226B<<<<<10"
        )
        data = parse_passport_mrz(text)
        self.assertFalse(data["valid_mrz"])
        self.assertFalse(data["checks"]["passport_number"])
