"""
In-app multi-select photo gallery picker for Pycam.

Matches the reference "Select Photo" design: an X to close, a "Select
Photo" album dropdown, an "Import(N)" button, and a 3-column checkbox grid
of the device's recent photos. This replaces (for the multi-select case)
the single-file Android system Chooser in ui/file_picker.py - that module
still has choose_image()/choose_pdf() for anywhere a single-file system
picker is preferred instead.

This is new, Android-native-heavy code (MediaStore queries, thumbnail
generation and permission requests all go through pyjnius) that could not
be exercised in the sandbox this was written in - there is no Android
runtime available there. Please test on a real device/emulator and expect
to iron out a few rough edges, especially around:
- exact permission strings/behaviour across Android versions,
- RecycleView performance with a very large photo library,
- thumbnail generation speed on low-end devices.

Integration notes:
- Add "photo_picker" to the app's ScreenManager alongside the other
  screens (scanner/preview/crop/editor/home).
- Whoever navigates here should set `app.photo_picker_return_screen`
  to the screen name to return to (defaults to "preview" if unset) -
  same pattern as ui/crop.py's `app.crop_source_path`.
- Add android.permission.READ_MEDIA_IMAGES (API 33+) and
  android.permission.READ_EXTERNAL_STORAGE (older) to buildozer.spec.
- Imported photos are appended to `app.active_session_pages` exactly like
  scanned pages, then the screen returns - EditorScreen/PreviewScreen need
  no changes to pick them up.
"""

import threading

from kivy.clock import Clock
from kivy.properties import ObjectProperty
from kivy.utils import platform
from kivymd.app import MDApp
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen
from kivymd.uix.snackbar import Snackbar

from ui.file_picker import (
    copy_media_image,
    get_or_create_thumbnail,
    list_media_images,
)

THUMB_SIZE_PX = 300
MAX_PHOTOS = 400
BATCH_SIZE = 12


class PhotoPickerScreen(MDScreen):
    status_label = ObjectProperty(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._selected_ids = set()
        self._id_to_index = {}
        self._album_menu = None
        self._loading = False
        self._cancel_requested = False

    # ---- Lifecycle -----------------------------------------------------

    def on_pre_enter(self, *args):
        self._selected_ids = set()
        self._id_to_index = {}
        self._cancel_requested = False
        self.photo_grid.data = []
        self._update_import_button()

        if platform != "android":
            self.status_label.text = (
                "Photo library access is only available in the Android build."
            )
            return

        self._request_permission_and_load()

    def on_leave(self, *args):
        # Any in-flight thumbnail/import thread checks this and bails out
        # early instead of touching widgets after the screen is gone.
        self._cancel_requested = True

    # ---- Permission + loading -----------------------------------------------------

    def _request_permission_and_load(self):
        try:
            from android.permissions import Permission, request_permissions
            from jnius import autoclass

            Build = autoclass("android.os.Build$VERSION")
            needed = (
                Permission.READ_MEDIA_IMAGES
                if int(Build.SDK_INT) >= 33
                else Permission.READ_EXTERNAL_STORAGE
            )

            def _on_result(_permissions, grants):
                if grants and all(grants):
                    Clock.schedule_once(lambda dt: self._start_loading(), 0)
                else:
                    Clock.schedule_once(
                        lambda dt: self._set_status(
                            "Photo access was denied. "
                            "Enable it from the app's system Settings."
                        ),
                        0,
                    )

            request_permissions([needed], _on_result)
        except Exception:
            # If the permission API itself is unavailable, still try to
            # load - some builds/OS versions may already have access.
            self._start_loading()

    def _start_loading(self):
        if self._loading:
            return
        self._loading = True
        self._set_status("Loading photos...")
        threading.Thread(target=self._load_images_thread, daemon=True).start()

    def _load_images_thread(self):
        images = list_media_images(limit=MAX_PHOTOS)

        app = MDApp.get_running_app()
        cache_dir = app.storage.get_temp_path("thumb_cache")
        if not isinstance(cache_dir, str):
            cache_dir = str(cache_dir)

        batch = []
        for item in images:
            if self._cancel_requested:
                return

            thumb_path = get_or_create_thumbnail(
                item["id"], cache_dir, size_px=THUMB_SIZE_PX
            )
            if not thumb_path:
                continue

            batch.append(
                {
                    "media_id": item["id"],
                    "thumb_path": thumb_path,
                    "checked": False,
                    "on_toggle": self.toggle_selection,
                }
            )

            if len(batch) >= BATCH_SIZE:
                to_append = list(batch)
                batch = []
                Clock.schedule_once(
                    lambda dt, rows=to_append: self._append_rows(rows), 0
                )

        if batch:
            to_append = list(batch)
            Clock.schedule_once(
                lambda dt, rows=to_append: self._append_rows(rows), 0
            )

        Clock.schedule_once(lambda dt: self._on_load_finished(len(images)), 0)

    def _append_rows(self, rows):
        if self._cancel_requested:
            return
        data = self.photo_grid.data
        start = len(data)
        for offset, row in enumerate(rows):
            self._id_to_index[row["media_id"]] = start + offset
        self.photo_grid.data = data + rows

    def _on_load_finished(self, total_found):
        self._loading = False
        if not self.photo_grid.data:
            self._set_status(
                "No photos found on this device."
                if total_found == 0
                else "Couldn't load any photo thumbnails."
            )
        else:
            self._set_status("")

    def _set_status(self, text):
        self.status_label.text = text

    # ---- Selection -----------------------------------------------------

    def toggle_selection(self, media_id):
        index = self._id_to_index.get(media_id)
        if index is None or index >= len(self.photo_grid.data):
            return

        if media_id in self._selected_ids:
            self._selected_ids.discard(media_id)
        else:
            self._selected_ids.add(media_id)

        data = self.photo_grid.data
        data[index] = dict(data[index], checked=media_id in self._selected_ids)
        self.photo_grid.data = data

        self._update_import_button()

    def _update_import_button(self):
        count = len(self._selected_ids)
        self.import_btn.text = f"Import({count})"
        self.import_btn.disabled = count == 0

    # ---- Album dropdown (stub - single "Recent Photos" bucket for now) --------

    def open_album_menu(self):
        if self._album_menu is None:
            self._album_menu = MDDropdownMenu(
                caller=self.select_label,
                items=[
                    {
                        "text": "Recent Photos",
                        "on_release": lambda: self._album_menu.dismiss(),
                    }
                ],
                width_mult=4,
            )
        self._album_menu.open()

    # ---- Import -----------------------------------------------------

    def import_selected(self):
        if not self._selected_ids or self._loading:
            return

        selected_ids = list(self._selected_ids)
        self.import_btn.disabled = True
        self._set_status(f"Importing 0 of {len(selected_ids)}...")

        threading.Thread(
            target=self._import_thread, args=(selected_ids,), daemon=True
        ).start()

    def _import_thread(self, media_ids):
        app = MDApp.get_running_app()
        copied_paths = []

        for done, media_id in enumerate(media_ids, start=1):
            if self._cancel_requested:
                return

            path = copy_media_image(media_id, app.storage)
            if path:
                copied_paths.append(path)

            Clock.schedule_once(
                lambda dt, n=done, total=len(media_ids): self._set_status(
                    f"Importing {n} of {total}..."
                ),
                0,
            )

        Clock.schedule_once(
            lambda dt: self._on_import_finished(copied_paths, len(media_ids)), 0
        )

    def _on_import_finished(self, copied_paths, requested_count):
        app = MDApp.get_running_app()

        if copied_paths:
            app.active_session_pages.extend(copied_paths)

        failed = requested_count - len(copied_paths)
        if failed:
            Snackbar(
                text=f"Imported {len(copied_paths)} photo(s); {failed} failed."
            ).open()

        if copied_paths:
            self._selected_ids = set()
            return_screen = getattr(app, "photo_picker_return_screen", "preview")
            app.go_to(return_screen)
        else:
            self._set_status("")
            self._update_import_button()
            if not copied_paths and requested_count:
                Snackbar(text="Couldn't import the selected photo(s).").open()

    # ---- Close -----------------------------------------------------

    def close_picker(self):
        app = MDApp.get_running_app()
        return_screen = getattr(app, "photo_picker_return_screen", "preview")
        app.go_to(return_screen)
