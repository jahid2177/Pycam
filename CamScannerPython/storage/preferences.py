"""
App preferences - a small JSON file in app storage, not a database
table (these are simple key/value settings, not records with an id/
created_at/updated_at shape the way documents are).

Every screen that reads a preference should fall back to DEFAULTS
rather than assume a key exists - preferences.json may be from an
older version of the app that didn't have a given setting yet.
"""

import json
import os
import threading

DEFAULTS = {
    "auto_capture": True,       # ScannerScreen's default for a new session
    "export_format": "pdf",     # pre-selected choice in the Export dialog: pdf | jpg | png
    "ocr_language": "english",  # pre-selected choice in the Run OCR dialog: english | bengali
    "theme_style": "Light",     # app.theme_cls.theme_style: Light | Dark
}


class AppPreferences:
    def __init__(self, storage_root: str):
        self._path = os.path.join(storage_root, "preferences.json")
        self._lock = threading.Lock()
        self._values = dict(DEFAULTS)
        self._load()

    def _load(self):
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                self._values.update(saved)
        except (json.JSONDecodeError, OSError):
            pass  # corrupt/unreadable prefs file - fall back to defaults rather than crash

    def _save(self):
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._values, f)
        except OSError:
            pass  # best-effort - a failed write shouldn't crash whatever screen changed a setting

    def get(self, key: str):
        return self._values.get(key, DEFAULTS.get(key))

    def set(self, key: str, value):
        with self._lock:
            self._values[key] = value
            self._save()
