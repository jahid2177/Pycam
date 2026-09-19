"""Persistent application preferences for Pycam."""

import json
import os
import threading

DEFAULTS = {
    "auto_capture": True,
    "auto_crop": True,
    "edge_sensitivity": "balanced",   # low | balanced | high
    "capture_delay": "normal",        # fast | normal | slow
    "flash_default": False,
    "high_resolution": True,
    "auto_enhance": True,
    "shutter_sound": True,
    "vibration": True,
    "grid_overlay": False,
    "camera_facing": "back",
    "export_format": "pdf",
    "pdf_page_size": "a4",           # auto | a4 | letter | legal
    "pdf_margin": "normal",           # none | small | normal | large
    "export_quality": "balanced",     # high | balanced | small
    "export_destination": "app",    # app | downloads | custom
    "export_tree_uri": "",
    "export_tree_label": "",
    "searchable_pdf": False,
    "ocr_language": "english",
    "auto_ocr": False,
    "keep_ocr_text": True,
    "theme_style": "Light",
    "app_language": "en",
    "analytics_enabled": False,
    "auto_temp_cleanup": True,
    "qr_history": [],
    "filename_template": "Scan_{date}_{time}",
    "app_lock_enabled": False,
    "app_lock_timeout": "immediate",  # immediate | 1min | 5min | 15min
    "biometric_unlock": False,
    "pin_salt": "",
    "pin_hash": "",
    "block_screenshots": True,
    "trash_retention": "30",       # never | 7 | 30 | 90 days
    "ai_base_url": "",
    "ai_model": "",
    "app_schema_version": 0,
    "last_seen_version": "",
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
            pass

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            temp = self._path + ".tmp"
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(self._values, f, ensure_ascii=False, indent=2)
            os.replace(temp, self._path)
        except OSError:
            pass

    def get(self, key: str):
        return self._values.get(key, DEFAULTS.get(key))

    def set(self, key: str, value):
        with self._lock:
            self._values[key] = value
            self._save()

    def reset(self):
        with self._lock:
            self._values = dict(DEFAULTS)
            self._save()
