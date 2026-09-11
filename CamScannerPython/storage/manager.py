"""
Filesystem layout for scanned pages, thumbnails, exported PDFs, and the
SQLite database.

On Android, app-private storage must come from the native context
(getExternalFilesDir / getFilesDir), not a hardcoded path - so this
module tries the Android bridge first and falls back to a local
`./app_data` folder when running on desktop (dev/testing) or when the
Android APIs aren't available.
"""

import os


class StorageManager:
    DOCS_DIR = "documents"
    THUMBS_DIR = "thumbnails"
    EXPORTS_DIR = "exports"
    TEMP_DIR = "temp"

    def __init__(self, app_name: str = "CamScannerPython"):
        self.app_name = app_name
        self.root = self._resolve_root_dir()
        self._ensure_dirs()

    def _resolve_root_dir(self) -> str:
        android_dir = self._android_files_dir()
        if android_dir:
            return android_dir
        # Desktop / dev fallback: keep everything under the project.
        base = os.path.join(os.path.expanduser("~"), ".camscannerpython")
        return base

    def _android_files_dir(self):
        """Return the app-private external files directory on Android,
        or None when not running on Android (e.g. desktop testing)."""
        try:
            from jnius import autoclass  # provided by pyjnius on Android

            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            context = activity.getApplicationContext()
            files_dir = context.getExternalFilesDir(None)
            if files_dir is None:
                files_dir = context.getFilesDir()
            return files_dir.getAbsolutePath()
        except Exception:
            return None

    def _ensure_dirs(self):
        for sub in (self.DOCS_DIR, self.THUMBS_DIR, self.EXPORTS_DIR, self.TEMP_DIR):
            os.makedirs(os.path.join(self.root, sub), exist_ok=True)

    # ---- Public path helpers -----------------------------------------

    def get_database_path(self) -> str:
        return os.path.join(self.root, "documents.db")

    def get_document_dir(self, document_id) -> str:
        path = os.path.join(self.root, self.DOCS_DIR, str(document_id))
        os.makedirs(path, exist_ok=True)
        return path

    def get_thumbnail_path(self, document_id) -> str:
        return os.path.join(self.root, self.THUMBS_DIR, f"{document_id}.jpg")

    def get_export_path(self, filename: str) -> str:
        return os.path.join(self.root, self.EXPORTS_DIR, filename)

    def get_temp_path(self, filename: str) -> str:
        return os.path.join(self.root, self.TEMP_DIR, filename)

    def clear_temp(self):
        temp_dir = os.path.join(self.root, self.TEMP_DIR)
        for entry in os.listdir(temp_dir):
            full_path = os.path.join(temp_dir, entry)
            try:
                if os.path.isfile(full_path):
                    os.remove(full_path)
            except OSError:
                pass
