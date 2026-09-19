"""Touch-friendly freehand annotation editor for scanned pages."""
from __future__ import annotations

from functools import partial

from kivy.graphics import Color, Line
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.slider import Slider
from kivy.uix.widget import Widget


_MODE_COLORS = {
    "pen": (0.88, 0.12, 0.12, 0.95),
    "highlight": (1.0, 0.85, 0.10, 0.42),
    "erase": (0.88, 0.88, 0.88, 0.75),
    "restore": (0.15, 0.82, 0.42, 0.85),
}


class _StrokeOverlay(Widget):
    def __init__(self, image_widget: Image, **kwargs):
        super().__init__(**kwargs)
        self.image_widget = image_widget
        self.mode = "pen"
        self.brush_px = float(dp(12))
        self.strokes = []
        self.redo_stack = []
        self._active = None
        self._active_line = None

    def _image_rect(self):
        nw, nh = self.image_widget.norm_image_size
        left = self.image_widget.x + (self.image_widget.width - nw) / 2.0
        bottom = self.image_widget.y + (self.image_widget.height - nh) / 2.0
        return left, bottom, max(1.0, nw), max(1.0, nh)

    def _normalise(self, x, y):
        left, bottom, width, height = self._image_rect()
        if not (left <= x <= left + width and bottom <= y <= bottom + height):
            return None
        return ((x - left) / width, (y - bottom) / height)

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        point = self._normalise(*touch.pos)
        if point is None:
            return super().on_touch_down(touch)
        _left, _bottom, width, height = self._image_rect()
        brush_frac = max(0.002, min(0.12, self.brush_px / max(1.0, min(width, height))))
        stroke = {"mode": self.mode, "points": [point], "brush": brush_frac}
        self._active = stroke
        self.redo_stack.clear()
        rgba = _MODE_COLORS.get(self.mode, _MODE_COLORS["pen"])
        with self.canvas:
            Color(*rgba)
            self._active_line = Line(points=[touch.x, touch.y], width=max(1.0, self.brush_px / 2.0), cap="round", joint="round")
        touch.grab(self)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self or self._active is None:
            return super().on_touch_move(touch)
        point = self._normalise(*touch.pos)
        if point is None:
            return True
        self._active["points"].append(point)
        if self._active_line is not None:
            self._active_line.points += [touch.x, touch.y]
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            if self._active is not None:
                self.strokes.append(self._active)
            self._active = None
            self._active_line = None
            return True
        return super().on_touch_up(touch)

    def set_mode(self, mode):
        if mode in _MODE_COLORS:
            self.mode = mode

    def undo(self):
        if not self.strokes:
            return
        self.redo_stack.append(self.strokes.pop())
        self.redraw()

    def redo(self):
        if not self.redo_stack:
            return
        self.strokes.append(self.redo_stack.pop())
        self.redraw()

    def clear_all(self):
        if self.strokes:
            self.redo_stack.extend(reversed(self.strokes))
        self.strokes = []
        self.redraw()

    def redraw(self):
        self.canvas.clear()
        left, bottom, width, height = self._image_rect()
        short_side = max(1.0, min(width, height))
        for stroke in self.strokes:
            points = stroke.get("points") or []
            if not points:
                continue
            flat = []
            for nx, ny in points:
                flat += [left + float(nx) * width, bottom + float(ny) * height]
            rgba = _MODE_COLORS.get(stroke.get("mode"), _MODE_COLORS["pen"])
            brush = max(1.0, float(stroke.get("brush", 0.012)) * short_side / 2.0)
            with self.canvas:
                Color(*rgba)
                Line(points=flat, width=brush, cap="round", joint="round")


class FreehandAnnotationView(ModalView):
    """Modal annotation editor with pen/highlighter/erase/restore brushes."""

    def __init__(self, image_path, before_save=None, on_saved=None, **kwargs):
        super().__init__(size_hint=(0.98, 0.98), auto_dismiss=False, background_color=(0, 0, 0, 0.96), **kwargs)
        self.image_path = image_path
        self.before_save = before_save
        self.on_saved = on_saved

        root = BoxLayout(orientation="vertical", spacing=dp(5), padding=dp(6))
        toolbar = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(4))
        self.status = Label(text="Pen • draw on the page", size_hint_x=1.35)
        toolbar.add_widget(self.status)
        for label, mode in (("PEN", "pen"), ("MARK", "highlight"), ("ERASE", "erase"), ("RESTORE", "restore")):
            btn = Button(text=label, size_hint_x=None, width=dp(76))
            btn.bind(on_release=partial(self._mode, mode))
            toolbar.add_widget(btn)
        root.add_widget(toolbar)

        stage = FloatLayout()
        self.image = Image(source=image_path, allow_stretch=True, keep_ratio=True)
        stage.add_widget(self.image)
        self.overlay = _StrokeOverlay(self.image)
        stage.add_widget(self.overlay)
        root.add_widget(stage)

        size_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        size_row.add_widget(Label(text="Brush", size_hint_x=None, width=dp(52)))
        slider = Slider(min=4, max=48, value=12, step=1)
        slider.bind(value=self._brush_changed)
        size_row.add_widget(slider)
        self.brush_label = Label(text="12", size_hint_x=None, width=dp(40))
        size_row.add_widget(self.brush_label)
        root.add_widget(size_row)

        actions = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(5))
        for text, callback in (
            ("UNDO", lambda *_: self.overlay.undo()),
            ("REDO", lambda *_: self.overlay.redo()),
            ("CLEAR", lambda *_: self.overlay.clear_all()),
            ("CANCEL", lambda *_: self.dismiss()),
            ("SAVE", self._save),
        ):
            button = Button(text=text)
            button.bind(on_release=callback)
            actions.add_widget(button)
        root.add_widget(actions)
        self.add_widget(root)

    def _mode(self, mode, *_args):
        self.overlay.set_mode(mode)
        labels = {
            "pen": "Pen • red freehand annotation",
            "highlight": "Highlighter • translucent yellow",
            "erase": "Eraser • inpaint selected marks",
            "restore": "Restore • recover original pixels",
        }
        self.status.text = labels.get(mode, mode.title())

    def _brush_changed(self, _slider, value):
        self.overlay.brush_px = float(value)
        self.brush_label.text = str(int(value))

    def _save(self, *_args):
        if not self.overlay.strokes:
            self.dismiss()
            return
        try:
            if callable(self.before_save):
                self.before_save()
            from image_processing.annotations import apply_freehand_strokes

            apply_freehand_strokes(self.image_path, list(self.overlay.strokes))
            if callable(self.on_saved):
                self.on_saved()
            self.dismiss()
        except Exception as exc:
            self.status.text = f"Save failed: {exc}"
