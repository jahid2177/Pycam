"""
Pycam application entry point.

This version intentionally keeps Android startup light and fault tolerant:
- only the Home screen is imported/created during boot;
- heavy screens (camera/OpenCV/OCR/gallery/editor) are imported lazily;
- each screen's KV file is loaded only when that screen is first opened;
- uncaught Python exceptions are written to crash_report.txt in app storage.

The goal is to prevent an optional feature/import from killing the whole app
immediately after tapping the launcher icon.
"""

import os
import sys
import traceback
from datetime import datetime

from kivy.core.window import Window
from kivy.lang import Builder
from kivy.uix.label import Label
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager
from kivymd.app import MDApp
from kivymd.uix.button import MDFlatButton
from kivymd.uix.dialog import MDDialog

from database.database import DocumentDatabase
from storage.manager import StorageManager
from storage.preferences import AppPreferences

# Home is the only application screen imported eagerly.
from ui.home import HomeScreen

APP_NAME = "Document Scanner"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KV_DIR = os.path.join(BASE_DIR, "ui", "kv")


# screen_name -> (module, class_name, kv_filename, constructor kwargs)
_LAZY_SCREENS = {
    "scanner": ("ui.scanner", "ScannerScreen", "scanner.kv", {}),
    "preview": ("ui.preview", "PreviewScreen", "preview.kv", {}),
    "crop": ("ui.crop", "CropScreen", "crop.kv", {}),
    "editor": ("ui.editor", "EditorScreen", None, {}),
    "documents": ("ui.documents", "DocumentsScreen", "documents.kv", {}),
    "settings": ("ui.settings", "SettingsScreen", None, {}),
    "tools": ("ui.tools", "ToolsScreen", None, {}),
    "extract_text_tool": (
        "ui.tool_workflows",
        "ToolWorkflowScreen",
        None,
        {"mode": "extract_text"},
    ),
    "passport_photo_tool": (
        "ui.tool_workflows",
        "ToolWorkflowScreen",
        None,
        {"mode": "passport_photo"},
    ),
    "photo_translation_tool": (
        "ui.tool_workflows",
        "ToolWorkflowScreen",
        None,
        {"mode": "photo_translation"},
    ),
    "scan_code_tool": (
        "ui.tool_workflows",
        "ToolWorkflowScreen",
        None,
        {"mode": "scan_code"},
    ),
    "photo_picker": (
        "storage.photo_picker",
        "PhotoPickerScreen",
        "photo_picker.kv",
        {},
    ),
}


class _ScreenLoadError(Screen):
    """Fallback screen shown when one optional screen cannot be imported."""

    def __init__(self, screen_name: str, error_text: str, **kwargs):
        super().__init__(name=screen_name, **kwargs)
        self.add_widget(
            Label(
                text=(
                    "This screen could not be opened.\n\n"
                    f"{error_text}\n\n"
                    "A detailed error was saved to crash_report.txt."
                ),
                halign="center",
                valign="middle",
                text_size=(Window.width * 0.88, None),
            )
        )


class ScannerApp(MDApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.title = APP_NAME
        self.icon = os.path.join(BASE_DIR, "assets", "icons", "app_icon.png")

        # Create storage first so even very early failures have a writable log.
        self.storage = StorageManager(app_name="CamScannerPython")
        self.db = DocumentDatabase(db_path=self.storage.get_database_path())
        self.prefs = AppPreferences(self.storage.root)

        self.active_session_pages = []
        self.latest_capture_path = None
        self.latest_raw_path = None
        self.crop_source_path = None
        self.crop_source_index = None
        self.selected_document_id = None
        self.editing_document_id = None
        self.photo_picker_return_screen = "preview"

        self._exit_dialog = None
        self._loaded_kv = set()
        self._old_excepthook = sys.excepthook
        sys.excepthook = self._handle_uncaught_exception

    # ------------------------------------------------------------------
    # Crash reporting
    # ------------------------------------------------------------------

    @property
    def crash_report_path(self) -> str:
        return os.path.join(self.storage.root, "crash_report.txt")

    def _write_crash_report(self, title: str, exc=None, extra: str = ""):
        try:
            lines = [
                "=" * 72,
                "PYCAM CRASH REPORT",
                "=" * 72,
                f"Time: {datetime.now().isoformat(timespec='seconds')}",
                f"Stage: {title}",
                "",
            ]
            if extra:
                lines.extend([extra, ""])
            if exc is not None:
                lines.extend(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )
            with open(self.crash_report_path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
        except Exception:
            pass

    def _handle_uncaught_exception(self, exc_type, exc_value, exc_tb):
        try:
            text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            self._write_crash_report("uncaught_exception", extra=text)
        finally:
            # Keep the normal Android/python logcat output too.
            try:
                self._old_excepthook(exc_type, exc_value, exc_tb)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # KV / screen loading
    # ------------------------------------------------------------------

    def _load_kv(self, filename: str):
        if not filename or filename in self._loaded_kv:
            return
        path = os.path.join(KV_DIR, filename)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"KV file not found: {path}")
        Builder.load_file(path)
        self._loaded_kv.add(filename)

    def _create_lazy_screen(self, screen_name: str):
        spec = _LAZY_SCREENS.get(screen_name)
        if spec is None:
            raise KeyError(f"Unknown screen: {screen_name}")

        module_name, class_name, kv_filename, kwargs = spec
        try:
            if kv_filename:
                self._load_kv(kv_filename)

            module = __import__(module_name, fromlist=[class_name])
            cls = getattr(module, class_name)
            screen = cls(name=screen_name, **dict(kwargs))
            self.screen_manager.add_widget(screen)
            return screen
        except Exception as exc:
            self._write_crash_report(
                f"load_screen:{screen_name}",
                exc=exc,
                extra=f"Module: {module_name}\nClass: {class_name}\nKV: {kv_filename}",
            )
            fallback = _ScreenLoadError(
                screen_name=screen_name,
                error_text=f"{type(exc).__name__}: {exc}",
            )
            self.screen_manager.add_widget(fallback)
            return fallback

    # ------------------------------------------------------------------
    # App lifecycle
    # ------------------------------------------------------------------

    def build(self):
        try:
            self.theme_cls.theme_style = self.prefs.get("theme_style") or "Light"
            self.theme_cls.primary_palette = "Teal"
            self.theme_cls.accent_palette = "Amber"

            # Do NOT load every KV file here. A single broken optional screen
            # must not prevent the app from reaching Home.
            self._load_kv("home.kv")

            self.screen_manager = ScreenManager(transition=NoTransition())
            self.screen_manager.add_widget(HomeScreen(name="home"))
            return self.screen_manager
        except Exception as exc:
            self._write_crash_report("build_home", exc=exc)
            # Re-raise so logcat still shows the exact original error.
            raise

    def on_start(self):
        try:
            self.db.initialize()
        except Exception as exc:
            # Database failure should not kill the process during startup.
            self._write_crash_report("database_initialize", exc=exc)

        Window.bind(on_keyboard=self._on_keyboard)

    def on_pause(self):
        return True

    def on_resume(self):
        pass

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def go_to(self, screen_name: str, **transition_kwargs):
        if screen_name != "home" and not self.screen_manager.has_screen(screen_name):
            self._create_lazy_screen(screen_name)

        if not self.screen_manager.has_screen(screen_name):
            screen_name = "home"

        for key, value in transition_kwargs.items():
            try:
                setattr(self.screen_manager.transition, key, value)
            except Exception:
                pass

        self.screen_manager.current = screen_name

    # ------------------------------------------------------------------
    # Back / exit
    # ------------------------------------------------------------------

    def _on_keyboard(self, window, key, scancode, codepoint, modifiers):
        if key not in (27, 1001):
            return False

        if self._exit_dialog is not None:
            return True

        if self.screen_manager.current != "home":
            self.go_to("home")
            return True

        self._show_exit_confirmation()
        return True

    def _show_exit_confirmation(self):
        if self._exit_dialog is not None:
            return

        dialog = MDDialog(
            title="Exit application?",
            text="Are you sure to exit?",
            auto_dismiss=False,
            buttons=[
                MDFlatButton(
                    text="NO",
                    on_release=lambda *_: self._dismiss_exit_dialog(),
                ),
                MDFlatButton(
                    text="YES",
                    on_release=lambda *_: self._confirm_exit(),
                ),
            ],
        )
        self._exit_dialog = dialog
        dialog.open()

    def _dismiss_exit_dialog(self):
        dialog = self._exit_dialog
        self._exit_dialog = None
        if dialog is not None:
            dialog.dismiss()

    def _confirm_exit(self):
        dialog = self._exit_dialog
        self._exit_dialog = None
        if dialog is not None:
            dialog.dismiss()
        self.stop()


if __name__ == "__main__":
    Window.softinput_mode = "below_target"
    ScannerApp().run()
