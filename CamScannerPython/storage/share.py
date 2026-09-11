"""
Native Android file sharing, via androidstorage4kivy's ShareSheet - the
same "Android-for-Python" ecosystem as camera4kivy (already used in
this project for the camera bridge), rather than hand-rolling Android's
FileProvider/content-URI setup ourselves. That setup (a <provider> tag
with the right authority, a matching <meta-data>, a correctly-scoped
file_paths.xml) is notoriously easy to get subtly wrong, and - unlike
the OCR bridges, which are single stable API calls - manifest merging
behavior varies across buildozer/p4a versions in ways this project has
no real device/build to verify against. androidstorage4kivy already
handles all of that internally.

Every earlier "Actual Android share-sheet integration lands in step 14"
comment (export, documents) refers to this module.

Requires (see buildozer.spec / requirements.txt):
    androidstorage4kivy

Cannot be exercised or verified outside a real Android device/emulator,
same limitation as every other native bridge in this project.
"""

import os

from kivy.utils import platform

SHARE_AVAILABLE = platform == "android"


def share_file(file_path: str):
    """Copy `file_path` (typically a private-storage export, e.g. from
    StorageManager.get_export_path) into Android shared storage and
    open the native ShareSheet for it, so the user can hand it straight
    to another app (Gmail, WhatsApp, Drive, etc.).

    Raises RuntimeError off-Android, if the file doesn't exist, or on
    any other bridge failure - callers should show that message rather
    than silently doing nothing.
    """
    if not SHARE_AVAILABLE:
        raise RuntimeError("Sharing to other apps is only available on Android")
    if not os.path.exists(file_path):
        raise RuntimeError(f"File not found: {file_path}")

    from androidstorage4kivy import SharedStorage, ShareSheet

    shared_storage = SharedStorage()
    shared_file = shared_storage.copy_to_shared(file_path)
    ShareSheet().share_file(shared_file)
