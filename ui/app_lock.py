"""App-lock screen and reusable PIN/biometric verification dialog."""

from kivy.clock import Clock
from kivy.metrics import dp
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField

from storage.security import verify_pin


def _biometric_enabled(app):
    return bool(app.prefs.get("biometric_unlock"))


def request_pin(title, on_success, *, text="Enter your app PIN to continue."):
    """Show PIN verification with optional Android biometric fallback."""
    app = MDApp.get_running_app()
    field = MDTextField(hint_text="PIN", password=True, input_filter="int", max_text_length=8)
    status = MDLabel(text="", theme_text_color="Secondary", size_hint_y=None, height=dp(30))
    box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8))
    box.add_widget(MDLabel(text=text, size_hint_y=None, height=dp(44)))
    box.add_widget(field)
    box.add_widget(status)

    def success():
        try:
            dialog.dismiss()
        except Exception:
            pass
        on_success()

    def verify(*_):
        if verify_pin(app.prefs, field.text or ""):
            success(); return
        field.text = ""; field.hint_text = "Incorrect PIN"; field.focus = True

    buttons = [MDFlatButton(text="CANCEL", on_release=lambda *_: dialog.dismiss())]

    def biometric(*_):
        try:
            from storage.biometric import authenticate
            status.text = "Waiting for biometric…"
            authenticate(title, success, lambda msg: setattr(status, "text", msg))
        except Exception as exc:
            status.text = f"Biometric unavailable: {exc}"

    if _biometric_enabled(app):
        buttons.append(MDFlatButton(text="BIOMETRIC", on_release=biometric))
    buttons.append(MDRaisedButton(text="UNLOCK", on_release=verify))

    dialog = MDDialog(title=title, type="custom", content_cls=box, buttons=buttons)
    field.bind(on_text_validate=verify)
    dialog.open(); field.focus = True
    if _biometric_enabled(app):
        Clock.schedule_once(lambda _dt: biometric(), .15)
    return dialog


class AppLockScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._failures = 0
        self._bio_attempted = False
        root = MDBoxLayout(orientation="vertical", padding=(dp(28), dp(60)), spacing=dp(18))
        root.add_widget(MDLabel(text="Document Scanner", halign="center", font_style="H5", size_hint_y=None, height=dp(54)))
        root.add_widget(MDLabel(text="App locked\nUse biometric or enter your PIN", halign="center", theme_text_color="Secondary", size_hint_y=None, height=dp(74)))
        self.pin_field = MDTextField(hint_text="PIN", password=True, input_filter="int", max_text_length=8, size_hint_x=.8, pos_hint={"center_x": .5})
        self.pin_field.bind(on_text_validate=lambda *_: self.unlock())
        root.add_widget(self.pin_field)
        buttons = MDBoxLayout(orientation="horizontal", adaptive_width=True, size_hint_y=None, height=dp(48), spacing=dp(10), pos_hint={"center_x": .5})
        self.bio_button = MDFlatButton(text="BIOMETRIC", on_release=lambda *_: self.unlock_biometric())
        buttons.add_widget(self.bio_button)
        buttons.add_widget(MDRaisedButton(text="UNLOCK", on_release=lambda *_: self.unlock()))
        root.add_widget(buttons)
        self.status = MDLabel(text="", halign="center", theme_text_color="Error", size_hint_y=None, height=dp(54))
        root.add_widget(self.status)
        self.add_widget(root)

    def on_pre_enter(self, *args):
        app = MDApp.get_running_app()
        self.pin_field.text = ""; self.status.text = ""; self._bio_attempted = False
        enabled = bool(app.prefs.get("biometric_unlock"))
        self.bio_button.disabled = not enabled
        self.bio_button.opacity = 1 if enabled else .35
        self.pin_field.focus = True
        if enabled:
            Clock.schedule_once(lambda _dt: self.unlock_biometric(auto=True), .2)

    def unlock_biometric(self, auto=False):
        app = MDApp.get_running_app()
        if not app.prefs.get("biometric_unlock"):
            if not auto: self.status.text = "Biometric unlock is disabled in Settings."
            return
        if auto and self._bio_attempted:
            return
        self._bio_attempted = True
        try:
            from storage.biometric import authenticate
            self.status.text = "Waiting for biometric…"
            authenticate("Unlock Document Scanner", app.unlock_app, lambda msg: setattr(self.status, "text", msg))
        except Exception as exc:
            self.status.text = f"Biometric unavailable: {exc}"

    def unlock(self):
        app = MDApp.get_running_app()
        if verify_pin(app.prefs, self.pin_field.text or ""):
            self._failures = 0; app.unlock_app(); return
        self._failures += 1; self.pin_field.text = ""; self.status.text = "Incorrect PIN"; self.pin_field.focus = True
