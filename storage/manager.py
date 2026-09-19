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
import json
import shutil
import re
from datetime import datetime, timezone


class StorageManager:
    DOCS_DIR = "documents"
    THUMBS_DIR = "thumbnails"
    EXPORTS_DIR = "exports"
    TEMP_DIR = "temp"
    DRAFTS_DIR = "draft_session"

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
        for sub in (self.DOCS_DIR, self.THUMBS_DIR, self.EXPORTS_DIR, self.TEMP_DIR, self.DRAFTS_DIR):
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

    @staticmethod
    def sanitize_filename(filename: str, fallback: str = "export") -> str:
        """Return a filesystem-safe basename and block path traversal."""
        value = os.path.basename(str(filename or "")).strip()
        stem, ext = os.path.splitext(value)
        stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', stem).strip(' ._')
        ext = re.sub(r'[^A-Za-z0-9.]', '', ext)
        if not stem:
            stem = fallback
        return stem[:120] + ext[:16]

    def get_export_path(self, filename: str, unique: bool = True) -> str:
        """Return a safe export path. Existing files are never overwritten by default."""
        safe = self.sanitize_filename(filename)
        directory = os.path.join(self.root, self.EXPORTS_DIR)
        os.makedirs(directory, exist_ok=True)
        candidate = os.path.join(directory, safe)
        if not unique or not os.path.exists(candidate):
            return candidate
        stem, ext = os.path.splitext(safe)
        counter = 2
        while True:
            candidate = os.path.join(directory, f"{stem}_{counter}{ext}")
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    def get_temp_path(self, filename: str) -> str:
        return os.path.join(self.root, self.TEMP_DIR, filename)

    def publish_export(self, file_path: str, prefs) -> str:
        """Copy a finished private export to the configured external destination.

        The original app-private export is intentionally retained so sharing,
        notifications, and recovery continue to have a normal filesystem path.
        """
        from storage.export_destination import publish_export
        return publish_export(file_path, prefs)


    # ---- Unfinished scan draft ---------------------------------------

    def _draft_dir(self) -> str:
        path = os.path.join(self.root, self.DRAFTS_DIR)
        os.makedirs(path, exist_ok=True)
        return path

    def save_session_draft(self, page_paths, editing_document_id=None, reason="manual") -> list:
        """Persist the current unfinished scan outside TEMP_DIR.

        Files are copied through a staging directory so this remains safe even
        when the active pages already point at a previous draft directory.
        Returns the copied draft page paths.
        """
        valid = [str(p) for p in (page_paths or []) if p and os.path.isfile(str(p))]
        if not valid:
            self.clear_session_draft()
            return []

        draft_dir = self._draft_dir()
        staging = draft_dir + '.staging'
        shutil.rmtree(staging, ignore_errors=True)
        os.makedirs(staging, exist_ok=True)

        copied = []
        try:
            for index, src in enumerate(valid, start=1):
                ext = os.path.splitext(src)[1].lower() or '.jpg'
                dst = os.path.join(staging, f'page_{index:03d}{ext}')
                shutil.copy2(src, dst)
                copied.append(dst)

            meta = {
                'editing_document_id': editing_document_id,
                'page_count': len(copied),
                'reason': str(reason or 'manual'),
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }
            with open(os.path.join(staging, 'draft.json'), 'w', encoding='utf-8') as fh:
                json.dump(meta, fh, ensure_ascii=False, indent=2)

            shutil.rmtree(draft_dir, ignore_errors=True)
            os.replace(staging, draft_dir)
            return [os.path.join(draft_dir, os.path.basename(path)) for path in copied]
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def load_session_draft(self):
        draft_dir = self._draft_dir()
        meta_path = os.path.join(draft_dir, 'draft.json')
        meta = {'editing_document_id': None}
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, 'r', encoding='utf-8') as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict):
                    meta.update(loaded)
            except (OSError, json.JSONDecodeError):
                pass

        pages = []
        for name in sorted(os.listdir(draft_dir)):
            if not name.startswith('page_'):
                continue
            path = os.path.join(draft_dir, name)
            if os.path.isfile(path):
                pages.append(path)
        return pages, meta.get('editing_document_id')

    def clear_session_draft(self):
        draft_dir = os.path.join(self.root, self.DRAFTS_DIR)
        shutil.rmtree(draft_dir, ignore_errors=True)
        os.makedirs(draft_dir, exist_ok=True)

    def clear_temp(self):
        import shutil
        temp_dir = os.path.join(self.root, self.TEMP_DIR)
        os.makedirs(temp_dir, exist_ok=True)
        for entry in os.listdir(temp_dir):
            full_path = os.path.join(temp_dir, entry)
            try:
                if os.path.isdir(full_path):
                    shutil.rmtree(full_path, ignore_errors=True)
                else:
                    os.remove(full_path)
            except OSError:
                pass

    def get_temp_size_bytes(self) -> int:
        temp_dir = os.path.join(self.root, self.TEMP_DIR)
        total = 0
        if not os.path.isdir(temp_dir):
            return 0
        for root, _dirs, files in os.walk(temp_dir):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
        return total

    def get_storage_size_bytes(self) -> int:
        total = 0
        for root, _dirs, files in os.walk(self.root):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
        return total
