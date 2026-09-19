"""Lightweight accessibility helpers for Kivy widgets.

Kivy renders into a custom surface rather than native Android Views, so these
helpers cannot promise native TalkBack contentDescription support.  They do
provide consistent semantic metadata for app code/tests and enforce practical
48dp minimum touch targets for interactive controls.
"""
from kivy.metrics import dp

MIN_TOUCH_DP = 48


def label_widget(widget, label, role="button"):
    if widget is None:
        return widget
    # Custom attributes are safe on Kivy EventDispatcher instances and are used
    # by our diagnostics/tests even where the platform cannot expose them.
    try:
        widget.accessibility_label = str(label or "")
        widget.accessibility_role = str(role or "")
    except Exception:
        pass
    return widget


def ensure_touch_target(widget, minimum_dp=MIN_TOUCH_DP):
    if widget is None:
        return widget
    minimum = dp(minimum_dp)
    try:
        if getattr(widget, "size_hint_y", None) is None and getattr(widget, "height", 0) < minimum:
            widget.height = minimum
        if getattr(widget, "size_hint_x", None) is None and getattr(widget, "width", 0) < minimum:
            widget.width = minimum
    except Exception:
        pass
    return widget


def audit_semantic_items(items):
    """Pure-Python friendly audit for (label, role, min_dp) tuples."""
    errors = []
    for index, item in enumerate(items):
        label, role, min_dp = item
        if not str(label or "").strip():
            errors.append(f"item {index}: missing label")
        if not str(role or "").strip():
            errors.append(f"item {index}: missing role")
        if float(min_dp) < MIN_TOUCH_DP:
            errors.append(f"item {index}: touch target below {MIN_TOUCH_DP}dp")
    return errors
