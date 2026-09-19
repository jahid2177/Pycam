"""Safe Android file Open/Share helpers.

Pycam creates exports in app-private storage first. Android apps must not be
handed those private filesystem paths directly. This module publishes the file
to Android shared storage with ``androidstorage4kivy`` and then uses its
ShareSheet wrapper, which works with a shared/content URI on modern Android.

The helper deliberately keeps a persistent ShareSheet instance. The upstream
library notes this is especially useful on Android < 10 because URI lifetime
can otherwise be tied to the ShareSheet object.
"""
from __future__ import annotations

import mimetypes
import os
from typing import Dict

try:
    from kivy.utils import platform
except Exception:  # unit-test/desktop fallback
    platform = "desktop"

SHARE_AVAILABLE = platform == "android"

# Python's mimetypes database differs slightly by host OS. Keep the document
# types Pycam exports deterministic for diagnostics/UI/tests.
_MIME_OVERRIDES: Dict[str, str] = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".json": "application/json",
    ".zip": "application/zip",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

_share_sheet = None


def guess_mime_type(file_path: str) -> str:
    """Return a stable MIME type for a Pycam export path."""
    ext = os.path.splitext(str(file_path or ""))[1].lower()
    if ext in _MIME_OVERRIDES:
        return _MIME_OVERRIDES[ext]
    guessed, _encoding = mimetypes.guess_type(str(file_path or ""))
    return guessed or "application/octet-stream"


def file_action_info(file_path: str) -> dict:
    """Validate a local export and return non-Android metadata.

    This helper is intentionally pure Python so CI can verify file-action
    behavior without importing PyJNIus or launching Android intents.
    """
    path = os.path.abspath(str(file_path or ""))
    if not file_path:
        raise ValueError("No file was provided.")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    size = os.path.getsize(path)
    if size <= 0:
        raise RuntimeError("The exported file is empty and cannot be opened or shared.")
    return {
        "path": path,
        "name": os.path.basename(path),
        "size": size,
        "mime": guess_mime_type(path),
    }


def _get_share_sheet():
    global _share_sheet
    if _share_sheet is None:
        from androidstorage4kivy import ShareSheet
        _share_sheet = ShareSheet()
    return _share_sheet


def _copy_to_shared(file_path: str):
    """Publish a private export and return androidstorage4kivy shared_file."""
    info = file_action_info(file_path)
    if not SHARE_AVAILABLE:
        raise RuntimeError("Opening or sharing with other apps is only available on Android.")

    from androidstorage4kivy import SharedStorage

    shared_file = SharedStorage().copy_to_shared(info["path"])
    if shared_file is None:
        raise RuntimeError(
            "Android could not create a shared copy of this file. "
            "Check storage availability and try again."
        )
    return shared_file


def share_file(file_path: str):
    """Open Android's native Share Sheet for a private Pycam export."""
    shared_file = _copy_to_shared(file_path)
    try:
        _get_share_sheet().share_file(shared_file)
    except Exception as exc:
        raise RuntimeError(f"Android could not share this file: {exc}") from exc
    return True


def open_file(file_path: str):
    """Open a private Pycam export in a compatible installed Android app.

    The file is first copied to Android shared storage, so no raw ``file://``
    URI or app-private path is exposed to another application.
    """
    shared_file = _copy_to_shared(file_path)
    try:
        _get_share_sheet().view_file(shared_file)
    except Exception as exc:
        raise RuntimeError(
            "No compatible Android app could open this file, or the open action failed: "
            f"{exc}"
        ) from exc
    return True
