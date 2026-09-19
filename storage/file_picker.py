"""
Android shared-storage picker for scanner imports.

Uses androidstorage4kivy's Chooser + SharedStorage APIs, which work with
Android content:// URIs across modern scoped-storage versions.
"""

import os
import shutil
import time
from pathlib import Path

from kivy.clock import Clock
from kivy.utils import platform


class FilePicker:
    def __init__(self):
        self._chooser = None
        self._callback = None
        self._error_callback = None
        self._mime = None

    def choose_image(self, callback, error_callback=None):
        self._choose("image/*", callback, error_callback)

    def choose_pdf(self, callback, error_callback=None):
        self._choose("application/pdf", callback, error_callback)

    def choose_zip(self, callback, error_callback=None):
        self._choose("application/zip", callback, error_callback)

    def _choose(self, mime, callback, error_callback):
        self._callback = callback
        self._error_callback = error_callback
        self._mime = mime

        if platform != "android":
            self._error("Storage picker is available in the Android build.")
            return

        try:
            from androidstorage4kivy import Chooser

            # Keep Chooser alive as an instance attribute until callback.
            self._chooser = Chooser(self._chooser_callback)
            self._chooser.choose_content(mime)
        except Exception as exc:
            self._error(f"Could not open storage picker: {exc}")

    def _chooser_callback(self, shared_file_list):
        try:
            if not shared_file_list:
                self._error("No file was selected.")
                return

            from androidstorage4kivy import SharedStorage

            shared = shared_file_list[0]
            private_path = SharedStorage().copy_from_shared(shared)

            if not private_path or not os.path.exists(private_path):
                self._error("The selected file could not be copied into the app.")
                return

            callback = self._callback
            self._reset()

            if callback:
                Clock.schedule_once(lambda dt, p=private_path: callback(p), 0)
        except Exception as exc:
            self._error(f"Could not read the selected file: {exc}")

    def _error(self, message):
        callback = self._error_callback
        self._reset()
        if callback:
            Clock.schedule_once(lambda dt, m=str(message): callback(m), 0)

    def _reset(self):
        self._chooser = None
        self._callback = None
        self._error_callback = None
        self._mime = None


def copy_to_app_temp(source_path, storage_manager, prefix="import"):
    suffix = Path(source_path).suffix.lower()
    if not suffix:
        suffix = ".bin"
    destination = storage_manager.get_temp_path(
        f"{prefix}_{int(time.time() * 1000)}{suffix}"
    )
    shutil.copy2(source_path, destination)
    return destination


def render_pdf_to_images(pdf_path, output_dir):
    """
    Render a selected PDF to JPEG pages with Android's native PdfRenderer.

    Returns a list of private filesystem paths that the existing editor
    can consume exactly like scanned pages.
    """
    if platform != "android":
        raise RuntimeError("PDF import rendering is available on Android.")

    from jnius import autoclass

    File = autoclass("java.io.File")
    ParcelFileDescriptor = autoclass("android.os.ParcelFileDescriptor")
    PdfRenderer = autoclass("android.graphics.pdf.PdfRenderer")
    Bitmap = autoclass("android.graphics.Bitmap")
    BitmapConfig = autoclass("android.graphics.Bitmap$Config")
    CompressFormat = autoclass("android.graphics.Bitmap$CompressFormat")
    FileOutputStream = autoclass("java.io.FileOutputStream")

    os.makedirs(output_dir, exist_ok=True)

    pfd = None
    renderer = None
    page_paths = []

    try:
        pfd = ParcelFileDescriptor.open(
            File(pdf_path),
            ParcelFileDescriptor.MODE_READ_ONLY,
        )
        renderer = PdfRenderer(pfd)
        page_count = int(renderer.getPageCount())

        if page_count <= 0:
            raise RuntimeError("The selected PDF contains no pages.")

        for index in range(page_count):
            page = renderer.openPage(index)
            bitmap = None
            stream = None

            try:
                width = int(page.getWidth())
                height = int(page.getHeight())

                # Render at 1.5x for a better editor/export result while
                # keeping memory reasonable on mid-range Android phones.
                target_w = max(1, int(width * 1.5))
                target_h = max(1, int(height * 1.5))

                bitmap = Bitmap.createBitmap(
                    target_w,
                    target_h,
                    BitmapConfig.ARGB_8888,
                )

                page.render(
                    bitmap,
                    None,
                    None,
                    PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY,
                )

                output_path = os.path.join(
                    output_dir,
                    f"pdf_page_{index + 1:03d}.jpg",
                )
                stream = FileOutputStream(output_path)
                bitmap.compress(CompressFormat.JPEG, 94, stream)
                stream.flush()
                page_paths.append(output_path)
            finally:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
                if bitmap is not None:
                    try:
                        bitmap.recycle()
                    except Exception:
                        pass
                page.close()

        return page_paths
    finally:
        if renderer is not None:
            try:
                renderer.close()
            except Exception:
                pass
        if pfd is not None:
            try:
                pfd.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# In-app photo gallery picker (custom multi-select grid, not the system
# Chooser). Backs ui/photo_picker.py.
#
# READ_MEDIA_IMAGES (Android 13+) or READ_EXTERNAL_STORAGE (older) must be
# granted before these are called - ui/photo_picker.py is responsible for
# that using android.permissions, since this module intentionally stays
# permission-request-free so it can also be imported/tested on desktop.
# ---------------------------------------------------------------------------

def _media_content_resolver():
    from jnius import autoclass

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    activity = PythonActivity.mActivity
    return activity.getContentResolver()


def list_media_images(limit=400, album=None, search=None):
    """
    Return recent device photos as a list of dicts:
        {"id": <MediaStore row id, str>, "date_added": <int, unix seconds>}

    Newest first. Returns [] on desktop or on any query failure - callers
    should treat an empty result as "show an empty/error state", not crash.
    """
    if platform != "android":
        return []

    try:
        from jnius import autoclass

        MediaStore = autoclass("android.provider.MediaStore$Images$Media")
        content_uri = MediaStore.EXTERNAL_CONTENT_URI

        # pyjnius converts a plain Python list into the Java String[]
        # this query() overload expects - no manual array construction
        # needed (and autoclass("java.lang.String[]") is not valid).
        projection = ["_id", "date_added", "display_name", "bucket_display_name", "relative_path"]

        resolver = _media_content_resolver()
        cursor = resolver.query(
            content_uri,
            projection,
            None,
            None,
            "date_added DESC",
        )

        if cursor is None:
            return []

        results = []
        try:
            id_index = cursor.getColumnIndexOrThrow("_id")
            date_index = cursor.getColumnIndexOrThrow("date_added")
            name_index = cursor.getColumnIndex("display_name")
            bucket_index = cursor.getColumnIndex("bucket_display_name")
            path_index = cursor.getColumnIndex("relative_path")

            while cursor.moveToNext() and len(results) < limit:
                name = cursor.getString(name_index) if name_index >= 0 else ""
                bucket = cursor.getString(bucket_index) if bucket_index >= 0 else ""
                relpath = cursor.getString(path_index) if path_index >= 0 else ""
                item = {
                    "id": str(cursor.getLong(id_index)),
                    "date_added": int(cursor.getLong(date_index)),
                    "display_name": name or "",
                    "bucket_name": bucket or "Other",
                    "relative_path": relpath or "",
                }
                if album and album != "Recent Photos" and item["bucket_name"] != album:
                    continue
                if search and search.lower() not in item["display_name"].lower():
                    continue
                results.append(item)
        finally:
            cursor.close()

        return results
    except Exception:
        return []


def list_media_albums(limit=1200):
    """Return available MediaStore album/bucket names, newest-oriented."""
    names = []
    seen = set()
    for item in list_media_images(limit=limit):
        name = item.get("bucket_name") or "Other"
        key = name.lower()
        if key not in seen:
            seen.add(key)
            names.append(name)
    return names


def get_or_create_thumbnail(media_id, cache_dir, size_px=300):
    """
    Return a private-storage JPEG thumbnail path for one MediaStore image,
    generating and caching it on first use.

    Uses ContentResolver.loadThumbnail (Android 10+ / API 29+). Older
    devices fall back to copy_media_image() + local downscale, which is
    slower but has no extra platform-version branching to maintain.
    """
    if platform != "android":
        return None

    os.makedirs(cache_dir, exist_ok=True)
    cached_path = os.path.join(cache_dir, f"thumb_{media_id}.jpg")
    if os.path.exists(cached_path):
        return cached_path

    try:
        from jnius import autoclass

        Build = autoclass("android.os.Build$VERSION")
        content_uri_str = f"content://media/external/images/media/{media_id}"
        Uri = autoclass("android.net.Uri")
        uri = Uri.parse(content_uri_str)
        resolver = _media_content_resolver()

        if int(Build.SDK_INT) >= 29:
            Size = autoclass("android.util.Size")
            CancellationSignal = autoclass("android.os.CancellationSignal")
            bitmap = resolver.loadThumbnail(
                uri, Size(size_px, size_px), CancellationSignal()
            )
        else:
            BitmapFactory = autoclass("android.graphics.BitmapFactory")
            stream = resolver.openInputStream(uri)
            try:
                bitmap = BitmapFactory.decodeStream(stream)
            finally:
                stream.close()

        if bitmap is None:
            return None

        CompressFormat = autoclass("android.graphics.Bitmap$CompressFormat")
        FileOutputStream = autoclass("java.io.FileOutputStream")

        out = FileOutputStream(cached_path)
        try:
            bitmap.compress(CompressFormat.JPEG, 85, out)
            out.flush()
        finally:
            out.close()
            try:
                bitmap.recycle()
            except Exception:
                pass

        return cached_path
    except Exception:
        return None


def copy_media_image(media_id, storage_manager, prefix="gallery"):
    """
    Copy one full-resolution MediaStore image into app-private storage.

    Returns the new private path, or None if the copy failed (permission
    revoked mid-session, item deleted from the gallery, etc.) - callers
    should skip that item rather than aborting the whole import.
    """
    if platform != "android":
        return None

    try:
        from jnius import autoclass

        Uri = autoclass("android.net.Uri")
        uri = Uri.parse(f"content://media/external/images/media/{media_id}")
        resolver = _media_content_resolver()

        stream = resolver.openInputStream(uri)
        if stream is None:
            return None

        destination = storage_manager.get_temp_path(
            f"{prefix}_{media_id}_{int(time.time() * 1000)}.jpg"
        )

        FileOutputStream = autoclass("java.io.FileOutputStream")
        out = FileOutputStream(destination)
        try:
            buffer = bytearray(64 * 1024)
            while True:
                read = stream.read(buffer)
                if read == -1:
                    break
                out.write(buffer, 0, read)
            out.flush()
        finally:
            out.close()
            stream.close()

        return destination
    except Exception:
        return None
