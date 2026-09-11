"""
Manual crop editor (step 7).

Shows the RAW captured photo (not the already-corrected one - editing
a crop should start from the original, uncropped pixels) with four
draggable corner handles, seeded from DocumentDetector's guess (or a
centered default rectangle if detection found nothing). "Apply crop"
runs the same `four_point_transform` used by step 6's automatic path,
just with the user's corners instead of the detector's.

All screen coordinate math lives in `ui/crop_geometry.py` and is unit
tested there; this module is deliberately thin - it just wires that
tested math to Kivy touch events and canvas drawing.
"""

import os
import threading

import numpy as np
import cv2

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.graphics import Color, Line, Ellipse
from kivy.uix.image import Image
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.relativelayout import RelativeLayout
from kivy.uix.widget import Widget
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.toolbar import MDTopAppBar
from kivymd.app import MDApp

from ui.crop_geometry import image_to_widget, widget_to_image
from scanner.detector import DocumentDetector
from image_processing.perspective import four_point_transform

HANDLE_RADIUS = dp(14)
HANDLE_TOUCH_RADIUS = dp(32)
OUTLINE_COLOR = (0.20, 0.85, 0.35, 0.9)
HANDLE_FILL = (1, 1, 1, 1)


def _distance(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


class CropOverlay(RelativeLayout):
    """Displays `image_path` and four draggable corner handles.

    Handle positions are stored as the source of truth in IMAGE pixel
    space (`self.image_quad`); widget-space positions are recomputed
    from that on every redraw, so resizing the screen never causes
    drift between the two spaces.
    """

    def __init__(self, image_path, initial_quad, **kwargs):
        super().__init__(**kwargs)
        self.image_path = image_path
        self.image_quad = [tuple(p) for p in initial_quad]
        self._dragging_index = None

        self.bg_image = Image(
            source=image_path, allow_stretch=True, keep_ratio=True, size_hint=(1, 1)
        )
        self.add_widget(self.bg_image)

        with self.canvas.after:
            Color(*OUTLINE_COLOR)
            self._quad_line = Line(points=[], width=dp(2), close=True)
            self._handle_ellipses = []
            self._handle_borders = []
            for _ in range(4):
                Color(*HANDLE_FILL)
                self._handle_ellipses.append(
                    Ellipse(pos=(0, 0), size=(HANDLE_RADIUS * 2, HANDLE_RADIUS * 2))
                )
                Color(*OUTLINE_COLOR)
                self._handle_borders.append(Line(circle=(0, 0, HANDLE_RADIUS), width=dp(2)))

        self.bind(pos=self._redraw, size=self._redraw)
        self.bg_image.bind(texture=lambda *a: self._redraw())

    def _get_image_size(self):
        tex = self.bg_image.texture
        if tex is None:
            return (1, 1)
        return tex.size

    def _widget_quad(self):
        image_size = self._get_image_size()
        return [image_to_widget(p, self.size, image_size) for p in self.image_quad]

    def _redraw(self, *args):
        widget_quad = self._widget_quad()
        flat = []
        for p in widget_quad:
            flat.extend(p)
        self._quad_line.points = flat
        for i, p in enumerate(widget_quad):
            self._handle_ellipses[i].pos = (p[0] - HANDLE_RADIUS, p[1] - HANDLE_RADIUS)
            self._handle_borders[i].circle = (p[0], p[1], HANDLE_RADIUS)

    def reset_to_quad(self, quad):
        self.image_quad = [tuple(p) for p in quad]
        self._redraw()

    def get_result_quad(self):
        return list(self.image_quad)

    # ---- Touch handling -----------------------------------------------

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        local = self.to_widget(*touch.pos)
        widget_quad = self._widget_quad()
        for i, p in enumerate(widget_quad):
            if _distance(local, p) <= HANDLE_TOUCH_RADIUS:
                self._dragging_index = i
                touch.grab(self)
                return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if touch.grab_current is self and self._dragging_index is not None:
            local = self.to_widget(*touch.pos)
            image_size = self._get_image_size()
            img_point = widget_to_image(local, self.size, image_size)
            self.image_quad[self._dragging_index] = img_point
            self._redraw()
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self._dragging_index = None
            return True
        return super().on_touch_up(touch)


class CropScreen(MDScreen):
    """Owns the toolbar/buttons; delegates all drawing and dragging to
    CropOverlay. Reads `app.crop_source_path` (set by PreviewScreen's
    "Adjust" button) on entry, writes the result back into
    `app.active_session_pages` and navigates back to preview."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.overlay = None
        self._raw_path = None

        root = MDBoxLayout(orientation="vertical")

        toolbar = MDTopAppBar(
            title="Adjust Corners",
            elevation=0,
            md_bg_color=(0, 0, 0, 1),
            specific_text_color=(1, 1, 1, 1),
        )
        toolbar.left_action_items = [["close", lambda x: self.cancel()]]
        toolbar.right_action_items = [["crop-free", lambda x: self.reset_to_auto()]]
        root.add_widget(toolbar)

        self.container = FloatLayout()
        root.add_widget(self.container)

        button_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(72),
            padding=(dp(24), dp(12)),
            spacing=dp(16),
            md_bg_color=(0, 0, 0, 1),
        )
        button_row.add_widget(
            MDFlatButton(
                text="CANCEL",
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1),
                on_release=lambda *a: self.cancel(),
            )
        )
        button_row.add_widget(Widget())
        button_row.add_widget(
            MDRaisedButton(text="APPLY CROP", on_release=lambda *a: self.apply_crop())
        )
        root.add_widget(button_row)

        self.add_widget(root)

    def on_pre_enter(self, *args):
        app = MDApp.get_running_app()
        self._raw_path = app.crop_source_path
        self.container.clear_widgets()

        quad = self._detect_initial_quad(self._raw_path)
        self.overlay = CropOverlay(
            image_path=self._raw_path, initial_quad=quad, size_hint=(1, 1)
        )
        self.container.add_widget(self.overlay)

    def _detect_initial_quad(self, path):
        """Seed the handles from auto-detection; if that finds nothing
        (or the file can't even be read), fall back to a rectangle
        inset 8% from each edge so the handles start somewhere
        reasonable rather than collapsed at the image's exact corners."""
        image = cv2.imread(path) if path else None
        if image is not None:
            quad = DocumentDetector().detect(image)
            if quad is not None:
                return [tuple(p) for p in quad]
            h, w = image.shape[:2]
        else:
            w, h = 1000, 1400
        mx, my = w * 0.08, h * 0.08
        return [(mx, my), (w - mx, my), (w - mx, h - my), (mx, h - my)]

    def reset_to_auto(self):
        if not self.overlay:
            return
        self.overlay.reset_to_quad(self._detect_initial_quad(self._raw_path))

    def cancel(self):
        MDApp.get_running_app().go_to("preview")

    def apply_crop(self):
        if not self.overlay or not self._raw_path:
            return
        quad = self.overlay.get_result_quad()
        threading.Thread(
            target=self._process_crop, args=(self._raw_path, quad), daemon=True
        ).start()

    def _process_crop(self, raw_path, quad):
        try:
            image = cv2.imread(raw_path)
            warped = four_point_transform(image, np.array(quad, dtype="float32"))
            output_path = os.path.splitext(raw_path)[0] + "_corrected.jpg"
            cv2.imwrite(output_path, warped)
        except Exception:
            output_path = raw_path  # keep the flow alive even if the warp failed
        Clock.schedule_once(lambda dt: self._on_crop_applied(output_path), 0)

    def _on_crop_applied(self, output_path):
        app = MDApp.get_running_app()
        if app.active_session_pages:
            app.active_session_pages[-1] = output_path
        app.latest_capture_path = output_path
        app.go_to("preview")
