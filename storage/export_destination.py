"""Android export destination helpers.

Exports are always created first in Pycam's app-private ``exports`` directory.
This module can then publish/copy the finished file to either Downloads/Pycam
or a user-selected Storage Access Framework (SAF) folder.

Keeping generation private first means the existing PDF/image/DOCX/XLSX/ZIP
writers continue to receive normal filesystem paths and do not need to know
about ``content://`` URIs.
"""

from __future__ import annotations

import mimetypes
import os
from typing import Callable, Optional

try:
    from kivy.clock import Clock
    from kivy.utils import platform
except Exception:  # lightweight desktop/unit-test fallback
    platform = "desktop"

    class _ImmediateClock:
        @staticmethod
        def schedule_once(callback, timeout=0):
            return callback(0)

    Clock = _ImmediateClock()

REQUEST_EXPORT_TREE = 61735

_picker_callback: Optional[Callable[[str, str], None]] = None
_picker_error_callback: Optional[Callable[[str], None]] = None
_picker_bound = False


def _safe_name(name: str) -> str:
    # StorageManager already sanitizes generated export names. Keep this helper
    # intentionally conservative for callers that hand us another private file.
    value = os.path.basename(str(name or "export"))
    return value or "export"


def _guess_mime(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


def choose_custom_export_folder(callback, error_callback=None):
    """Open Android's ACTION_OPEN_DOCUMENT_TREE folder picker.

    ``callback(tree_uri, label)`` is invoked on the Kivy thread after the user
    selects a folder. Persistent read/write permission is requested so the same
    destination can be reused after an app restart.
    """
    global _picker_callback, _picker_error_callback, _picker_bound

    if platform != "android":
        if error_callback:
            Clock.schedule_once(lambda _dt: error_callback(
                "Custom export folders are available in the Android build."
            ), 0)
        return

    try:
        from android import activity
        from jnius import autoclass

        Intent = autoclass("android.content.Intent")

        _picker_callback = callback
        _picker_error_callback = error_callback

        if not _picker_bound:
            activity.bind(on_activity_result=_on_activity_result)
            _picker_bound = True

        intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
        flags = (
            Intent.FLAG_GRANT_READ_URI_PERMISSION
            | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
            | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION
        )
        intent.addFlags(flags)
        from storage.android_compat import start_activity_for_result_checked
        start_activity_for_result_checked(
            intent,
            REQUEST_EXPORT_TREE,
            "No Android document provider is available for choosing an export folder.",
        )
    except Exception as exc:
        _dispatch_picker_error(f"Could not open folder picker: {exc}")


def _on_activity_result(request_code, result_code, intent):
    if int(request_code) != REQUEST_EXPORT_TREE:
        return

    try:
        from jnius import autoclass

        Activity = autoclass("android.app.Activity")
        Intent = autoclass("android.content.Intent")
        DocumentsContract = autoclass("android.provider.DocumentsContract")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")

        if int(result_code) != int(Activity.RESULT_OK) or intent is None:
            _dispatch_picker_error("Folder selection was cancelled.")
            return

        uri = intent.getData()
        if uri is None:
            _dispatch_picker_error("No export folder was selected.")
            return

        resolver = PythonActivity.mActivity.getContentResolver()
        take_flags = int(intent.getFlags()) & (
            Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
        )
        try:
            resolver.takePersistableUriPermission(uri, take_flags)
        except Exception:
            # Some providers do not offer persistable grants. The current grant
            # may still work for this app session, so keep the selected URI.
            pass

        uri_string = str(uri.toString())
        label = "Custom folder"
        try:
            tree_id = str(DocumentsContract.getTreeDocumentId(uri))
            # Common IDs look like ``primary:Documents/My Folder``.
            tail = tree_id.split(":", 1)[-1].rstrip("/")
            if tail:
                label = tail.split("/")[-1] or label
        except Exception:
            pass

        callback = _picker_callback
        _clear_picker_callbacks()
        if callback:
            Clock.schedule_once(lambda _dt, u=uri_string, l=label: callback(u, l), 0)
    except Exception as exc:
        _dispatch_picker_error(f"Could not remember the selected folder: {exc}")


def _clear_picker_callbacks():
    global _picker_callback, _picker_error_callback
    _picker_callback = None
    _picker_error_callback = None


def _dispatch_picker_error(message: str):
    callback = _picker_error_callback
    _clear_picker_callbacks()
    if callback:
        Clock.schedule_once(lambda _dt, m=str(message): callback(m), 0)


def publish_export(file_path: str, prefs) -> str:
    """Copy a finished private export to the configured external destination.

    Returns a user-facing destination description. In ``app`` mode no extra
    copy occurs and the original private path is returned.
    """
    if not file_path or not os.path.isfile(file_path):
        raise FileNotFoundError(file_path or "Export file does not exist")

    mode = str(prefs.get("export_destination") or "app").lower()
    if mode == "app":
        return file_path

    if platform != "android":
        raise RuntimeError("External export destinations are available in the Android build.")

    if mode == "downloads":
        return _copy_to_downloads(file_path)

    if mode == "custom":
        tree_uri = str(prefs.get("export_tree_uri") or "").strip()
        if not tree_uri:
            raise RuntimeError("Choose a custom export folder in Settings first.")
        return _copy_to_tree(file_path, tree_uri)

    raise RuntimeError(f"Unknown export destination: {mode}")


def _copy_to_downloads(file_path: str) -> str:
    from androidstorage4kivy import SharedStorage
    from jnius import autoclass

    Environment = autoclass("android.os.Environment")
    shared = SharedStorage().copy_to_shared(
        file_path,
        Environment.DIRECTORY_DOWNLOADS,
        f"Pycam/{_safe_name(file_path)}",
    )
    if shared is None:
        raise RuntimeError("Could not save the export to Downloads/Pycam.")
    return f"Downloads/Pycam/{_safe_name(file_path)}"


def _tree_children_names(resolver, DocumentsContract, tree_uri):
    """Return names already present in a SAF tree; failures are non-fatal."""
    names = set()
    cursor = None
    try:
        document_id = DocumentsContract.getTreeDocumentId(tree_uri)
        children_uri = DocumentsContract.buildChildDocumentsUriUsingTree(tree_uri, document_id)
        cursor = resolver.query(
            children_uri,
            [DocumentsContract.Document.COLUMN_DISPLAY_NAME],
            None,
            None,
            None,
        )
        if cursor is not None:
            idx = cursor.getColumnIndex(DocumentsContract.Document.COLUMN_DISPLAY_NAME)
            while cursor.moveToNext():
                if idx >= 0:
                    value = cursor.getString(idx)
                    if value:
                        names.add(str(value))
    except Exception:
        pass
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
    return names


def _unique_display_name(filename: str, existing_names) -> str:
    filename = _safe_name(filename)
    if filename not in existing_names:
        return filename
    stem, ext = os.path.splitext(filename)
    counter = 2
    while True:
        candidate = f"{stem}_{counter}{ext}"
        if candidate not in existing_names:
            return candidate
        counter += 1


def _copy_to_tree(file_path: str, tree_uri_string: str) -> str:
    from jnius import autoclass

    Uri = autoclass("android.net.Uri")
    DocumentsContract = autoclass("android.provider.DocumentsContract")
    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    FileInputStream = autoclass("java.io.FileInputStream")
    File = autoclass("java.io.File")

    tree_uri = Uri.parse(tree_uri_string)
    resolver = PythonActivity.mActivity.getContentResolver()
    parent_id = DocumentsContract.getTreeDocumentId(tree_uri)
    parent_uri = DocumentsContract.buildDocumentUriUsingTree(tree_uri, parent_id)

    existing = _tree_children_names(resolver, DocumentsContract, tree_uri)
    display_name = _unique_display_name(os.path.basename(file_path), existing)
    mime = _guess_mime(display_name)
    new_uri = DocumentsContract.createDocument(resolver, parent_uri, mime, display_name)
    if new_uri is None:
        raise RuntimeError("The selected folder did not allow creating the export file.")

    src = None
    dst = None
    try:
        src = FileInputStream(File(file_path))
        dst = resolver.openOutputStream(new_uri, "w")
        if dst is None:
            raise RuntimeError("Could not open the selected folder for writing.")

        # A small Java-byte buffer works across the Android versions supported
        # by python-for-android and avoids loading a large PDF/ZIP fully in RAM.
        from jnius import autoclass as _autoclass
        ByteBuffer = _autoclass("java.nio.ByteBuffer")
        buffer = ByteBuffer.allocate(64 * 1024)
        array = buffer.array()
        while True:
            count = int(src.read(array))
            if count < 0:
                break
            if count:
                dst.write(array, 0, count)
        dst.flush()
    except Exception:
        try:
            DocumentsContract.deleteDocument(resolver, new_uri)
        except Exception:
            pass
        raise
    finally:
        if dst is not None:
            try:
                dst.close()
            except Exception:
                pass
        if src is not None:
            try:
                src.close()
            except Exception:
                pass

    return f"{display_name} (custom folder)"
