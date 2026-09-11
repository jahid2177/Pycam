"""
Preview screen - shown immediately after a page is captured and
perspective-corrected (step 6 runs on the scanner screen before
navigating here, so `latest_capture_path` already points at the
corrected image when correction succeeded, or the raw photo when it
didn't). As of step 8, also lets the user pick an enhancement filter
(Original / Auto Enhance / Grayscale / B&W / Color Boost) via a chip
row; each filter's output is cached per-page so switching back and
forth doesn't reprocess the image every time.

This is still fundamentally the review step: retake / adjust corners /
add another page / finish. Whichever filter is selected when the user
leaves this screen (via any exit) is what stays in
`app.active_session_pages` and `app.latest_capture_path` - `_show_path`
keeps those in sync on every filter change, so retake/discard/finish
never need to know filters exist.
"""

import os
import threading

import cv2

from kivy.clock import Clock
from kivy.properties import ObjectProperty
from kivymd.uix.screen import MDScreen
from kivymd.uix.button import MDFlatButton
from kivymd.app import MDApp

from image_processing.filters import apply_filter, FILTER_LABELS

SELECTED_COLOR = (0.20, 0.85, 0.35, 1)
UNSELECTED_COLOR = (1, 1, 1, 1)


class PreviewScreen(MDScreen):
    preview_image = ObjectProperty(None)
    filter_row = ObjectProperty(None)
    processing_label = ObjectProperty(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._base_path = None  # this page's image as shown on entry, before any filter
        self._filter_cache = {}  # filter_name -> already-rendered file path
        self._selected_filter = "original"
        self._filter_buttons = {}
        self._processing = False

    # ---- Lifecycle -----------------------------------------------------

    def on_pre_enter(self, *args):
        app = MDApp.get_running_app()
        path = app.latest_capture_path

        self._base_path = path
        self._filter_cache = {"original": path} if path else {}
        self._selected_filter = "original"
        self._processing = False
        if path:
            self.preview_image.source = path
        self._build_filter_row()

    def _build_filter_row(self):
        if not self.filter_row:
            return
        self.filter_row.clear_widgets()
        self._filter_buttons = {}
        for name, label in FILTER_LABELS.items():
            is_selected = name == self._selected_filter
            btn = MDFlatButton(
                text=label,
                theme_text_color="Custom",
                text_color=SELECTED_COLOR if is_selected else UNSELECTED_COLOR,
                on_release=lambda inst, n=name: self.select_filter(n),
            )
            self._filter_buttons[name] = btn
            self.filter_row.add_widget(btn)

    # ---- Filters -----------------------------------------------------

    def select_filter(self, name: str):
        if self._processing or name == self._selected_filter or not self._base_path:
            return
        self._selected_filter = name
        self._highlight_selected()

        if name in self._filter_cache:
            self._show_path(self._filter_cache[name])
            return

        self._set_processing(True)
        threading.Thread(target=self._run_filter, args=(name,), daemon=True).start()

    def _run_filter(self, name: str):
        try:
            image = cv2.imread(self._base_path)
            filtered = apply_filter(image, name)
            output_path = f"{os.path.splitext(self._base_path)[0]}_{name}.jpg"
            cv2.imwrite(output_path, filtered)
        except Exception:
            output_path = self._base_path  # never lose the page over a filter error
        Clock.schedule_once(lambda dt: self._on_filter_ready(name, output_path), 0)

    def _on_filter_ready(self, name: str, output_path: str):
        self._filter_cache[name] = output_path
        self._set_processing(False)
        if self._selected_filter == name:
            self._show_path(output_path)

    def _show_path(self, path: str):
        app = MDApp.get_running_app()
        self.preview_image.source = path
        # Keep the session's record in sync with whatever is on screen -
        # guarded so this only touches active_session_pages when this
        # preview is genuinely showing a page from the current session.
        if app.active_session_pages and app.latest_capture_path in app.active_session_pages:
            idx = app.active_session_pages.index(app.latest_capture_path)
            app.active_session_pages[idx] = path
        app.latest_capture_path = path

    def _highlight_selected(self):
        for name, btn in self._filter_buttons.items():
            btn.text_color = SELECTED_COLOR if name == self._selected_filter else UNSELECTED_COLOR

    def _set_processing(self, busy: bool):
        self._processing = busy
        if self.processing_label:
            self.processing_label.opacity = 1 if busy else 0
        for btn in self._filter_buttons.values():
            btn.disabled = busy

    # ---- Navigation -----------------------------------------------------

    def adjust_crop(self):
        app = MDApp.get_running_app()
        app.crop_source_path = app.latest_raw_path or app.latest_capture_path
        app.go_to("crop")

    def retake(self):
        app = MDApp.get_running_app()
        if app.active_session_pages and app.active_session_pages[-1] == app.latest_capture_path:
            app.active_session_pages.pop()
        app.go_to("scanner")

    def scan_another(self):
        MDApp.get_running_app().go_to("scanner")

    def finish_session(self):
        MDApp.get_running_app().go_to("editor")

    def discard(self):
        app = MDApp.get_running_app()
        if app.active_session_pages and app.active_session_pages[-1] == app.latest_capture_path:
            app.active_session_pages.pop()
        app.go_to("home")
