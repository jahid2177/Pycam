import os
import tempfile
import unittest
from pathlib import Path


class FastIntegrationSmokeTests(unittest.TestCase):
    def test_static_integration(self):
        from storage.integration_check import run_static_integration_check
        report = run_static_integration_check(Path.cwd())
        self.assertTrue(report["ok"], report["issues"])

    def test_database_lifecycle_and_integrity(self):
        from database.database import DocumentDatabase
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "smoke.db")
            with DocumentDatabase(db_path) as db:
                result = db.integrity_check()
                self.assertTrue(result.get("ok"), result)
            self.assertIsNone(db._conn)

    def test_android_12_16_static_compatibility(self):
        from storage.android_compat import static_android_compatibility_audit
        report = static_android_compatibility_audit(Path.cwd())
        self.assertTrue(report["ok"], report["issues"])
        self.assertGreaterEqual(report["checks_passed"], 10)

    def test_release_preflight_non_strict(self):
        import importlib.util
        script = Path.cwd() / ".github" / "scripts" / "release_preflight.py"
        spec = importlib.util.spec_from_file_location("release_preflight", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report = module.run_preflight(strict_assets=False)
        self.assertTrue(report["ok"], report["errors"])
        self.assertGreaterEqual(report["checks_passed"], 30)

    def test_core_python_sources_compile(self):
        import py_compile
        roots = ("main.py", "database/database.py", "storage/integration_check.py", "storage/health_check.py", "storage/android_compat.py")
        for rel in roots:
            py_compile.compile(rel, doraise=True)


if __name__ == "__main__":
    unittest.main()
