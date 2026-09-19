"""
Reusable export-options dialog used by both Home and Files screens.

callback signature:
    callback(format_name, options_dict)

format_name:
    "pdf" | "jpg" | "png"

options_dict keys:
    page_size: auto | a4 | letter | legal
    orientation: auto | portrait | landscape
    margin_pt: float
    quality: high | balanced | small
"""

from kivy.metrics import dp

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import (
    MDFlatButton,
    MDRaisedButton,
)
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.app import MDApp


ACTIVE = (
    0.05,
    0.52,
    0.46,
    1,
)
INACTIVE = (
    0.18,
    0.22,
    0.28,
    1,
)


FORMAT_OPTIONS = (
    ("PDF", "pdf"),
    ("JPG", "jpg"),
    ("PNG", "png"),
)

PAGE_SIZE_OPTIONS = (
    ("Auto", "auto"),
    ("A4", "a4"),
    ("Letter", "letter"),
    ("Legal", "legal"),
)

ORIENTATION_OPTIONS = (
    ("Auto", "auto"),
    ("Portrait", "portrait"),
    ("Landscape", "landscape"),
)

MARGIN_OPTIONS = (
    ("None", 0.0),
    ("Small", 12.0),
    ("Normal", 24.0),
    ("Large", 36.0),
)

QUALITY_OPTIONS = (
    ("High", "high"),
    ("Balanced", "balanced"),
    ("Small", "small"),
)


class _ChoiceRow(MDBoxLayout):
    def __init__(
        self,
        choices,
        selected,
        on_change,
        **kwargs,
    ):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            spacing=dp(2),
            **kwargs,
        )

        self.choices = list(
            choices
        )
        self.selected = selected
        self.on_change = on_change
        self.buttons = {}

        for label, value in self.choices:
            button = MDFlatButton(
                text=label,
                theme_text_color="Custom",
                text_color=(
                    ACTIVE
                    if value == selected
                    else INACTIVE
                ),
                on_release=lambda inst, v=value:
                    self._select(v),
            )

            self.buttons[
                value
            ] = button
            self.add_widget(
                button
            )

    def _select(
        self,
        value,
    ):
        self.selected = value

        for key, button in (
            self.buttons.items()
        ):
            button.text_color = (
                ACTIVE
                if key == value
                else INACTIVE
            )

        self.on_change(
            value
        )


def _section(
    title,
    choices,
    selected,
    on_change,
):
    box = MDBoxLayout(
        orientation="vertical",
        size_hint_y=None,
        height=dp(72),
        spacing=0,
    )

    box.add_widget(
        MDLabel(
            text=title,
            font_style="Caption",
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(24),
        )
    )

    box.add_widget(
        _ChoiceRow(
            choices,
            selected,
            on_change,
        )
    )

    return box


def show_export_dialog(
    title: str,
    preferred_format: str,
    callback,
):
    try:
        prefs = MDApp.get_running_app().prefs
        default_page = prefs.get("pdf_page_size") or "a4"
        margin_name = prefs.get("pdf_margin") or "normal"
        default_quality = prefs.get("export_quality") or "balanced"
        default_searchable = bool(prefs.get("searchable_pdf"))
    except Exception:
        default_page, margin_name, default_quality, default_searchable = "a4", "normal", "balanced", False

    margin_map = {"none": 0.0, "small": 12.0, "normal": 24.0, "large": 36.0}
    state = {
        "format": (preferred_format if preferred_format in ("pdf", "jpg", "png") else "pdf"),
        "page_size": default_page if default_page in ("auto", "a4", "letter", "legal") else "a4",
        "orientation": "auto",
        "margin_pt": margin_map.get(margin_name, 24.0),
        "quality": default_quality if default_quality in ("high", "balanced", "small") else "balanced",
        "searchable": default_searchable,
    }

    content = MDBoxLayout(
        orientation="vertical",
        size_hint_y=None,
        height=dp(430),
        spacing=dp(2),
        padding=(
            dp(4),
            dp(4),
        ),
    )

    def set_value(
        key,
        value,
    ):
        state[key] = value

        # Fixed-page options are meaningful only for PDF.
        pdf_mode = (
            state["format"]
            == "pdf"
        )

        for section in (
            page_section,
            orientation_section,
            margin_section,
            searchable_section,
        ):
            section.disabled = (
                not pdf_mode
            )
            section.opacity = (
                1.0
                if pdf_mode
                else 0.38
            )

    format_section = _section(
        "Format",
        FORMAT_OPTIONS,
        state["format"],
        lambda value:
            set_value(
                "format",
                value,
            ),
    )

    page_section = _section(
        "PDF page size",
        PAGE_SIZE_OPTIONS,
        state["page_size"],
        lambda value:
            set_value(
                "page_size",
                value,
            ),
    )

    orientation_section = _section(
        "Orientation",
        ORIENTATION_OPTIONS,
        state["orientation"],
        lambda value:
            set_value(
                "orientation",
                value,
            ),
    )

    margin_section = _section(
        "Margin",
        MARGIN_OPTIONS,
        state["margin_pt"],
        lambda value:
            set_value(
                "margin_pt",
                value,
            ),
    )

    quality_section = _section(
        "Quality / compression",
        QUALITY_OPTIONS,
        state["quality"],
        lambda value:
            set_value(
                "quality",
                value,
            ),
    )

    searchable_section = _section(
        "Searchable PDF",
        (("Off", False), ("On", True)),
        state["searchable"],
        lambda value: set_value("searchable", value),
    )

    content.add_widget(
        format_section
    )
    content.add_widget(
        page_section
    )
    content.add_widget(
        orientation_section
    )
    content.add_widget(
        margin_section
    )
    content.add_widget(
        quality_section
    )
    content.add_widget(
        searchable_section
    )

    dialog = None

    def export_now(*args):
        options = {
            "page_size": state[
                "page_size"
            ],
            "orientation": state[
                "orientation"
            ],
            "margin_pt": float(
                state["margin_pt"]
            ),
            "quality": state[
                "quality"
            ],
            "searchable": bool(
                state["searchable"]
            ),
        }

        dialog.dismiss()

        callback(
            state["format"],
            options,
        )

    dialog = MDDialog(
        title=title,
        type="custom",
        content_cls=content,
        buttons=[
            MDFlatButton(
                text="CANCEL",
                on_release=lambda *args:
                    dialog.dismiss(),
            ),
            MDRaisedButton(
                text="EXPORT",
                on_release=export_now,
            ),
        ],
    )

    # Initialize enable/opacity correctly.
    set_value(
        "format",
        state["format"],
    )

    dialog.open()
    return dialog
