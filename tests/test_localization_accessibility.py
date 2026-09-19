import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class LocalizationAccessibilityTests(unittest.TestCase):
    def _localization_ns(self):
        ns = {}
        exec((ROOT / "storage" / "localization.py").read_text(encoding="utf-8"), ns)
        return ns

    def test_english_bangla_catalogues_match(self):
        ns = self._localization_ns()
        translations = ns["TRANSLATIONS"]
        self.assertEqual(set(translations["en"]), set(translations["bn"]))
        self.assertFalse(ns["missing_translation_keys"]()["bn"])

    def test_every_visible_tool_title_has_translation(self):
        tree = ast.parse((ROOT / "ui" / "tools.py").read_text(encoding="utf-8"))
        sections = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TOOL_SECTIONS" for t in node.targets):
                sections = ast.literal_eval(node.value)
                break
        self.assertIsNotNone(sections)
        ns = self._localization_ns()
        en, bn = ns["TRANSLATIONS"]["en"], ns["TRANSLATIONS"]["bn"]
        for section_key, tools in sections:
            self.assertIn(section_key, en); self.assertIn(section_key, bn)
            for _icon, title_key, _route in tools:
                self.assertIn(title_key, en); self.assertIn(title_key, bn)
                self.assertTrue(en[title_key].strip()); self.assertTrue(bn[title_key].strip())

    def test_accessibility_hooks_and_minimum_target(self):
        source = (ROOT / "storage" / "accessibility.py").read_text(encoding="utf-8")
        self.assertIn("MIN_TOUCH_DP = 48", source)
        for rel in ("ui/navigation.py", "ui/tools.py", "ui/settings.py"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("label_widget", text)
            self.assertIn("ensure_touch_target", text)

if __name__ == "__main__":
    unittest.main()
