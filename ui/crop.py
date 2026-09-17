"""
Manual Crop & Adjust screen for Pycam.

Key behavior:
- auto-detect is used only when entering a new crop session or pressing Reset;
- user-adjusted corners are the source of truth;
- Rotate Left/Right rotates BOTH the image and existing manual corners;
- rotation never triggers document re-detection;
- crop handles remain constrained to the visible image;
- dragging a corner shows a magnified view of the local source pixels;
- Apply Crop uses the same four_point_transform as automatic correction.

No new Python/Android dependency is introduced.
"""

import os
import threading
import time

import cv2
import numpy as np

from kivy.clock import Clock
from kivy.graphics import (
    Color,
    Ellipse,
    Line,
    Rectangle,
)
from kivy.metrics import dp
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.relativelayout import RelativeLayout
from kivy.uix.widget import Widget

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import (
    MDFlatButton,
    MDRaisedButton,
)
from kivymd.uix.screen import MDScreen
from kivymd.uix.toolbar import MDTopAppBar

from image_processing.perspective import (
    four_point_transform,
)
from scanner.detector import (
    DocumentDetector,
    order_points,
)
from ui.crop_geometry import (
    clamp_quad,
    image_to_widget,
    rotate_quad_90,
    widget_to_image,
)


HANDLE_RADIUS = dp(14)
HANDLE_TOUCH_RADIUS = dp(34)

OUTLINE_COLOR = (
    0.12,
    0.88,
    0.67,
    0.98,
)
HANDLE_FILL = (
    1,
    1,
    1,
    1,
)

MAGNIFIER_SIZE = dp(116)
MAGNIFIER_SOURCE_RADIUS_PX = 55


def _distance(a, b):
    return (
        (
            a[0] - b[0]
        ) ** 2
        + (
            a[1] - b[1]
        ) ** 2
    ) ** 0.5


class CropOverlay(RelativeLayout):
    """
    Image + draggable four-corner crop overlay.

    `image_quad` in source-image pixels is always the source of truth.
    """

    def __init__(
        self,
        image_path,
        initial_quad,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.image_path = image_path
        self.image_quad = [
            tuple(p)
            for p in initial_quad
        ]

        self._dragging_index = None

        self.bg_image = Image(
            source=image_path,
            allow_stretch=True,
            keep_ratio=True,
            size_hint=(1, 1),
        )
        self.add_widget(
            self.bg_image
        )

        with self.canvas.after:
            Color(
                *OUTLINE_COLOR
            )
            self._quad_line = Line(
                points=[],
                width=dp(2.4),
                close=True,
                joint="round",
            )

            self._handle_ellipses = []
            self._handle_borders = []

            for _ in range(4):
                Color(
                    *HANDLE_FILL
                )
                self._handle_ellipses.append(
                    Ellipse(
                        pos=(0, 0),
                        size=(
                            HANDLE_RADIUS * 2,
                            HANDLE_RADIUS * 2,
                        ),
                    )
                )

                Color(
                    *OUTLINE_COLOR
                )
                self._handle_borders.append(
                    Line(
                        circle=(
                            0,
                            0,
                            HANDLE_RADIUS,
                        ),
                        width=dp(2),
                    )
                )

            # Magnifier is hidden offscreen until a handle is dragged.
            Color(
                0,
                0,
                0,
                0.80,
            )
            self._magnifier_bg = Ellipse(
                pos=(-1000, -1000),
                size=(
                    MAGNIFIER_SIZE
                    + dp(8),
                    MAGNIFIER_SIZE
                    + dp(8),
                ),
            )

            Color(
                1,
                1,
                1,
                1,
            )
            self._magnifier_rect = Rectangle(
                pos=(-1000, -1000),
                size=(
                    MAGNIFIER_SIZE,
                    MAGNIFIER_SIZE,
                ),
            )

            Color(
                *OUTLINE_COLOR
            )
            self._magnifier_border = Line(
                circle=(
                    -1000,
                    -1000,
                    MAGNIFIER_SIZE / 2,
                ),
                width=dp(2.5),
            )

            self._magnifier_cross_h = Line(
                points=[],
                width=dp(1.5),
            )
            self._magnifier_cross_v = Line(
                points=[],
                width=dp(1.5),
            )

        self.bind(
            pos=self._redraw,
            size=self._redraw,
        )
        self.bg_image.bind(
            texture=lambda *args:
                self._on_texture_ready()
        )

    # ------------------------------------------------------------------
    # Image / quad
    # ------------------------------------------------------------------

    def _on_texture_ready(self):
        self._redraw()

    def _get_image_size(self):
        texture = self.bg_image.texture

        if texture is None:
            return (
                1,
                1,
            )

        return texture.size

    def _widget_quad(self):
        image_size = (
            self._get_image_size()
        )

        return [
            image_to_widget(
                point,
                self.size,
                image_size,
            )
            for point
            in self.image_quad
        ]

    def _redraw(self, *args):
        widget_quad = (
            self._widget_quad()
        )

        flat = []
        for point in widget_quad:
            flat.extend(point)

        self._quad_line.points = flat

        for index, point in enumerate(
            widget_quad
        ):
            self._handle_ellipses[
                index
            ].pos = (
                point[0]
                - HANDLE_RADIUS,
                point[1]
                - HANDLE_RADIUS,
            )

            self._handle_borders[
                index
            ].circle = (
                point[0],
                point[1],
                HANDLE_RADIUS,
            )

    def set_image_and_quad(
        self,
        image_path,
        quad,
    ):
        """
        Atomically update source image + already transformed manual corners.

        No auto detection occurs here.
        """
        self.image_path = image_path
        self.image_quad = [
            tuple(p)
            for p in quad
        ]

        self._hide_magnifier()

        self.bg_image.source = (
            image_path
        )
        self.bg_image.reload()

        Clock.schedule_once(
            lambda dt:
                self._redraw(),
            0,
        )

    def reset_to_quad(self, quad):
        self.image_quad = [
            tuple(p)
            for p in quad
        ]
        self._redraw()

    def get_result_quad(self):
        return list(
            self.image_quad
        )

    # ------------------------------------------------------------------
    # Magnifier
    # ------------------------------------------------------------------

    def _hide_magnifier(self):
        self._magnifier_bg.pos = (
            -1000,
            -1000,
        )
        self._magnifier_rect.pos = (
            -1000,
            -1000,
        )
        self._magnifier_border.circle = (
            -1000,
            -1000,
            MAGNIFIER_SIZE / 2,
        )
        self._magnifier_cross_h.points = []
        self._magnifier_cross_v.points = []

    def _update_magnifier(
        self,
        image_point,
        finger_widget_point,
    ):
        texture = (
            self.bg_image.texture
        )

        if texture is None:
            return

        image_w, image_h = (
            self._get_image_size()
        )

        if (
            image_w <= 1
            or image_h <= 1
        ):
            return

        x, y = image_point

        radius = float(
            MAGNIFIER_SOURCE_RADIUS_PX
        )

        x0 = max(
            0.0,
            x - radius,
        )
        x1 = min(
            float(image_w),
            x + radius,
        )
        y0 = max(
            0.0,
            y - radius,
        )
        y1 = min(
            float(image_h),
            y + radius,
        )

        u0 = x0 / image_w
        u1 = x1 / image_w

        # Image coordinates are top-left; texture V is bottom-left.
        v_top = 1.0 - (
            y0 / image_h
        )
        v_bottom = 1.0 - (
            y1 / image_h
        )

        self._magnifier_rect.texture = (
            texture
        )
        self._magnifier_rect.tex_coords = [
            u0,
            v_bottom,
            u1,
            v_bottom,
            u1,
            v_top,
            u0,
            v_top,
        ]

        # Place magnifier above the dragged point when possible; otherwise
        # below it. Keep it inside the overlay.
        finger_x, finger_y = (
            finger_widget_point
        )

        mag_x = finger_x - (
            MAGNIFIER_SIZE / 2
        )
        mag_y = (
            finger_y
            + dp(58)
        )

        if (
            mag_y
            + MAGNIFIER_SIZE
            > self.height - dp(8)
        ):
            mag_y = (
                finger_y
                - MAGNIFIER_SIZE
                - dp(58)
            )

        mag_x = min(
            max(
                mag_x,
                dp(8),
            ),
            max(
                dp(8),
                self.width
                - MAGNIFIER_SIZE
                - dp(8),
            ),
        )

        mag_y = min(
            max(
                mag_y,
                dp(8),
            ),
            max(
                dp(8),
                self.height
                - MAGNIFIER_SIZE
                - dp(8),
            ),
        )

        self._magnifier_rect.pos = (
            mag_x,
            mag_y,
        )

        self._magnifier_bg.pos = (
            mag_x - dp(4),
            mag_y - dp(4),
        )

        center_x = (
            mag_x
            + MAGNIFIER_SIZE / 2
        )
        center_y = (
            mag_y
            + MAGNIFIER_SIZE / 2
        )

        self._magnifier_border.circle = (
            center_x,
            center_y,
            MAGNIFIER_SIZE / 2,
        )

        cross = dp(12)
        self._magnifier_cross_h.points = [
            center_x - cross,
            center_y,
            center_x + cross,
            center_y,
        ]
        self._magnifier_cross_v.points = [
            center_x,
            center_y - cross,
            center_x,
            center_y + cross,
        ]

    # ------------------------------------------------------------------
    # Touch handling
    # ------------------------------------------------------------------

    def on_touch_down(self, touch):
        if not self.collide_point(
            *touch.pos
        ):
            return super().on_touch_down(
                touch
            )

        local = self.to_widget(
            *touch.pos
        )

        widget_quad = (
            self._widget_quad()
        )

        nearest_index = None
        nearest_distance = None

        for index, point in enumerate(
            widget_quad
        ):
            distance = _distance(
                local,
                point,
            )

            if (
                distance
                <= HANDLE_TOUCH_RADIUS
                and (
                    nearest_distance
                    is None
                    or distance
                    < nearest_distance
                )
            ):
                nearest_index = index
                nearest_distance = (
                    distance
                )

        if nearest_index is not None:
            self._dragging_index = (
                nearest_index
            )
            touch.grab(self)

            self._update_magnifier(
                self.image_quad[
                    nearest_index
                ],
                local,
            )

            return True

        return super().on_touch_down(
            touch
        )

    def on_touch_move(self, touch):
        if (
            touch.grab_current is self
            and self._dragging_index
            is not None
        ):
            local = self.to_widget(
                *touch.pos
            )

            image_size = (
                self._get_image_size()
            )

            image_point = (
                widget_to_image(
                    local,
                    self.size,
                    image_size,
                )
            )

            # Keep every point explicitly inside current image bounds.
            clamped = clamp_quad(
                [image_point] * 4,
                image_size,
            )[0]

            self.image_quad[
                self._dragging_index
            ] = clamped

            self._redraw()
            self._update_magnifier(
                clamped,
                local,
            )

            return True

        return super().on_touch_move(
            touch
        )

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self._dragging_index = None
            self._hide_magnifier()
            return True

        return super().on_touch_up(
            touch
        )


class CropScreen(MDScreen):
    """
    Manual Crop & Adjust screen.

    Rotation deliberately transforms the existing manual quad. The detector is
    NOT called again unless the user taps Reset.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.overlay = None
        self._source_path = None
        self._working_path = None
        self._temporary_rotated_paths = []

        root = MDBoxLayout(
            orientation="vertical"
        )

        toolbar = MDTopAppBar(
            title="Crop & Adjust",
            elevation=0,
            md_bg_color=(
                0,
                0,
                0,
                1,
            ),
            specific_text_color=(
                1,
                1,
                1,
                1,
            ),
        )

        toolbar.left_action_items = [
            [
                "close",
                lambda x:
                    self.cancel(),
            ]
        ]

        # Reset is the ONLY action that intentionally runs auto detection.
        toolbar.right_action_items = [
            [
                "backup-restore",
                lambda x:
                    self.reset_to_auto(),
            ]
        ]

        root.add_widget(
            toolbar
        )

        self.container = (
            FloatLayout()
        )
        root.add_widget(
            self.container
        )

        controls = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(76),
            padding=(
                dp(12),
                dp(10),
            ),
            spacing=dp(8),
            md_bg_color=(
                0,
                0,
                0,
                1,
            ),
        )

        controls.add_widget(
            MDFlatButton(
                text="ROTATE LEFT",
                theme_text_color="Custom",
                text_color=(
                    1,
                    1,
                    1,
                    1,
                ),
                on_release=lambda *args:
                    self.rotate(
                        clockwise=False
                    ),
            )
        )

        controls.add_widget(
            MDFlatButton(
                text="ROTATE RIGHT",
                theme_text_color="Custom",
                text_color=(
                    1,
                    1,
                    1,
                    1,
                ),
                on_release=lambda *args:
                    self.rotate(
                        clockwise=True
                    ),
            )
        )

        controls.add_widget(
            Widget()
        )

        controls.add_widget(
            MDRaisedButton(
                text="APPLY CROP",
                on_release=lambda *args:
                    self.apply_crop(),
            )
        )

        root.add_widget(
            controls
        )

        self.add_widget(
            root
        )

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    def on_pre_enter(self, *args):
        app = MDApp.get_running_app()

        requested_path = (
            app.crop_source_path
        )

        # A fresh entry starts from the requested source. Within this screen,
        # rotate operations only mutate _working_path and the current quad.
        self._cleanup_temp_rotations()

        self._source_path = (
            requested_path
        )
        self._working_path = (
            requested_path
        )

        self.container.clear_widgets()

        quad = self._detect_initial_quad(
            self._working_path
        )

        self.overlay = CropOverlay(
            image_path=self._working_path,
            initial_quad=quad,
            size_hint=(1, 1),
        )

        self.container.add_widget(
            self.overlay
        )

    def on_leave(self, *args):
        # Do not delete current working temp synchronously before Preview has
        # loaded it after Apply. _on_crop_applied writes a separate corrected
        # file, so rotation temps can safely be cleaned here.
        self._cleanup_temp_rotations()

    def _detect_initial_quad(
        self,
        path,
    ):
        """
        Initial/Reset-only auto detection.
        """
        image = (
            cv2.imread(path)
            if path
            else None
        )

        if image is not None:
            quad = (
                DocumentDetector()
                .detect(image)
            )

            if quad is not None:
                return [
                    tuple(p)
                    for p
                    in order_points(
                        quad
                    )
                ]

            height, width = (
                image.shape[:2]
            )
        else:
            width, height = (
                1000,
                1400,
            )

        margin_x = (
            width * 0.08
        )
        margin_y = (
            height * 0.08
        )

        return [
            (
                margin_x,
                margin_y,
            ),
            (
                width - margin_x,
                margin_y,
            ),
            (
                width - margin_x,
                height - margin_y,
            ),
            (
                margin_x,
                height - margin_y,
            ),
        ]

    def reset_to_auto(self):
        if (
            not self.overlay
            or not self._working_path
        ):
            return

        self.overlay.reset_to_quad(
            self._detect_initial_quad(
                self._working_path
            )
        )

    # ------------------------------------------------------------------
    # Rotate while preserving manual quad
    # ------------------------------------------------------------------

    def rotate(
        self,
        clockwise: bool,
    ):
        if (
            not self.overlay
            or not self._working_path
        ):
            return

        image = cv2.imread(
            self._working_path,
            cv2.IMREAD_COLOR,
        )

        if image is None:
            return

        old_height, old_width = (
            image.shape[:2]
        )

        current_quad = (
            self.overlay.get_result_quad()
        )

        # Transform current USER corners before touching the image. No detector
        # call occurs here.
        rotated_quad = rotate_quad_90(
            current_quad,
            (
                old_width,
                old_height,
            ),
            clockwise,
        )

        rotated_image = cv2.rotate(
            image,
            (
                cv2.ROTATE_90_CLOCKWISE
                if clockwise
                else cv2.ROTATE_90_COUNTERCLOCKWISE
            ),
        )

        app = MDApp.get_running_app()

        temp_path = (
            app.storage.get_temp_path(
                "crop_rotate_"
                f"{int(time.time() * 1000)}.jpg"
            )
        )

        success = cv2.imwrite(
            temp_path,
            rotated_image,
            [
                int(
                    cv2.IMWRITE_JPEG_QUALITY
                ),
                97,
            ],
        )

        if not success:
            return

        self._temporary_rotated_paths.append(
            temp_path
        )
        self._working_path = (
            temp_path
        )

        new_height, new_width = (
            rotated_image.shape[:2]
        )

        rotated_quad = (
            clamp_quad(
                rotated_quad,
                (
                    new_width,
                    new_height,
                ),
            )
        )

        self.overlay.set_image_and_quad(
            self._working_path,
            rotated_quad,
        )

    # ------------------------------------------------------------------
    # Navigation / apply
    # ------------------------------------------------------------------

    def cancel(self):
        MDApp.get_running_app().go_to(
            "preview"
        )

    def apply_crop(self):
        if (
            not self.overlay
            or not self._working_path
        ):
            return

        quad = (
            self.overlay.get_result_quad()
        )

        threading.Thread(
            target=self._process_crop,
            args=(
                self._working_path,
                quad,
            ),
            daemon=True,
        ).start()

    def _process_crop(
        self,
        source_path,
        quad,
    ):
        try:
            image = cv2.imread(
                source_path,
                cv2.IMREAD_COLOR,
            )

            if image is None:
                raise ValueError(
                    "Could not read crop source."
                )

            warped = (
                four_point_transform(
                    image,
                    np.asarray(
                        quad,
                        dtype=np.float32,
                    ),
                )
            )

            # Always use a separate final file so temporary rotated sources can
            # be safely removed when leaving this screen.
            app = (
                MDApp.get_running_app()
            )

            output_path = (
                app.storage.get_temp_path(
                    "manual_crop_"
                    f"{int(time.time() * 1000)}.jpg"
                )
            )

            success = cv2.imwrite(
                output_path,
                warped,
                [
                    int(
                        cv2.IMWRITE_JPEG_QUALITY
                    ),
                    97,
                ],
            )

            if not success:
                raise IOError(
                    "Could not save cropped image."
                )

        except Exception:
            # Keep scanner flow alive if a user creates an invalid polygon.
            output_path = (
                source_path
            )

        Clock.schedule_once(
            lambda dt, path=output_path:
                self._on_crop_applied(
                    path
                ),
            0,
        )

    def _on_crop_applied(
        self,
        output_path,
    ):
        app = (
            MDApp.get_running_app()
        )

        if app.active_session_pages:
            app.active_session_pages[
                -1
            ] = output_path

        app.latest_capture_path = (
            output_path
        )

        # The manually cropped result becomes the new working page. We do not
        # overwrite latest_raw_path; users can still reopen Adjust from the
        # original source if PreviewScreen intentionally chooses it.
        app.go_to(
            "preview"
        )

    def _cleanup_temp_rotations(self):
        for path in list(
            self._temporary_rotated_paths
        ):
            try:
                if (
                    path
                    and os.path.isfile(path)
                ):
                    os.remove(path)
            except OSError:
                pass

        self._temporary_rotated_paths = []
