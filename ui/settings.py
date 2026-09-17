"""
Settings screen - reads/writes AppPreferences (storage/preferences.py).

Each setting here is read by the screen it affects rather than pushed
around at set-time, keeping this screen simple:
  - auto_capture   -> ui/scanner.py reads it as the starting value of
                       ScannerScreen.auto_capture_enabled on entry
  - export_format  -> ui/home.py and ui/documents.py's export dialogs
                       pre-highlight this choice
  - ocr_language   -> same, for the Run OCR dialogs
  - theme_style    -> applied immediately here (live theme change),
                       AND read at next app launch in main.py's build()
"""

from kivy.metrics import dp
from kivy.uix.widget import Widget
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton
from kivymd.uix.label import MDLabel
from kivymd.uix.toolbar import MDTopAppBar
from kivymd.uix.selectioncontrol import MDSwitch
from kivymd.app import MDApp

from ui.navigation import BottomNavigationBar

SELECTED_COLOR = (0.20, 0.85, 0.35, 1)


class ChoiceRow(MDBoxLayout):
    """A labeled row of mutually-exclusive flat-button choices (used
    for export format and OCR language) - simple enough not to need a
    full radio-button widget, and matches the same button-row pattern
    already used in the Export/Run OCR dialogs."""

    def __init__(self, label, options, current_value, on_choose, **kwargs):
        super().__init__(orientation="vertical", size_hint_y=None, height=dp(72),
                          padding=(dp(16), dp(4)), **kwargs)
        self.add_widget(MDLabel(text=label, theme_text_color="Secondary", font_style="Caption"))

        row = MDBoxLayout(orientation="horizontal", spacing=dp(8))
        self._buttons = {}
        for value, text in options:
            btn = MDFlatButton(
                text=text,
                theme_text_color="Custom",
                text_color=SELECTED_COLOR if value == current_value else (0, 0, 0, 0.87),
                on_release=lambda inst, v=value: self._choose(v, on_choose),
            )
            self._buttons[value] = btn
            row.add_widget(btn)
        self.add_widget(row)

    def _choose(self, value, on_choose):
        for v, btn in self._buttons.items():
            btn.text_color = SELECTED_COLOR if v == value else (0, 0, 0, 0.87)
        on_choose(value)


class SettingsScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        root = MDBoxLayout(orientation="vertical")

        toolbar = MDTopAppBar(title="Settings", elevation=0)
        root.add_widget(toolbar)

        body = MDBoxLayout(orientation="vertical", padding=(0, dp(8)))

        # ---- Auto-capture toggle -----------------------------------------------------
        auto_row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(56),
                                padding=(dp(16), 0))
        auto_row.add_widget(MDLabel(text="Auto-capture when scanning"))
        self.auto_switch = MDSwitch(active=False)  # value set in on_pre_enter
        self.auto_switch.bind(active=self._on_auto_capture_changed)
        auto_row.add_widget(self.auto_switch)
        body.add_widget(auto_row)

        # ---- Default export format -----------------------------------------------------
        self.export_row = ChoiceRow(
            "Default export format",
            [("pdf", "PDF"), ("jpg", "JPG"), ("png", "PNG")],
            current_value="pdf",  # corrected in on_pre_enter
            on_choose=self._on_export_format_changed,
        )
        body.add_widget(self.export_row)

        # ---- Default OCR language -----------------------------------------------------
        self.ocr_row = ChoiceRow(
            "Default OCR language",
            [("english", "ENGLISH"), ("bengali", "BENGALI")],
            current_value="english",
            on_choose=self._on_ocr_language_changed,
        )
        body.add_widget(self.ocr_row)

        # ---- Theme -----------------------------------------------------
        theme_row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(56),
                                 padding=(dp(16), 0))
        theme_row.add_widget(MDLabel(text="Dark theme"))
        self.theme_switch = MDSwitch(active=False)
        self.theme_switch.bind(active=self._on_theme_changed)
        theme_row.add_widget(self.theme_switch)
        body.add_widget(theme_row)

        body.add_widget(Widget())  # push everything above to the top
        root.add_widget(body)
        root.add_widget(BottomNavigationBar(selected="settings"))

        self.add_widget(root)

    def on_pre_enter(self, *args):
        app = MDApp.get_running_app()
        # Rebuild the choice rows so they reflect the current saved
        # preference (in case it was changed elsewhere, or this is the
        # first time defaults are being read).
        self.auto_switch.active = bool(app.prefs.get("auto_capture"))
        self.theme_switch.active = app.prefs.get("theme_style") == "Dark"
        self._sync_choice_row(self.export_row, app.prefs.get("export_format"))
        self._sync_choice_row(self.ocr_row, app.prefs.get("ocr_language"))

    def _sync_choice_row(self, row: ChoiceRow, current_value):
        for value, btn in row._buttons.items():
            btn.text_color = SELECTED_COLOR if value == current_value else (0, 0, 0, 0.87)

    # ---- Handlers -----------------------------------------------------

    def _on_auto_capture_changed(self, instance, value):
        MDApp.get_running_app().prefs.set("auto_capture", bool(value))

    def _on_export_format_changed(self, value):
        MDApp.get_running_app().prefs.set("export_format", value)

    def _on_ocr_language_changed(self, value):
        MDApp.get_running_app().prefs.set("ocr_language", value)

    def _on_theme_changed(self, instance, value):
        app = MDApp.get_running_app()
        style = "Dark" if value else "Light"
        app.prefs.set("theme_style", style)
        app.theme_cls.theme_style = style

    def go_home(self):
        MDApp.get_running_app().go_to("home")
