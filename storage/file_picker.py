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
