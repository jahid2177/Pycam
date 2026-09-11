"""
CamScannerPython - main application entry point.

Responsible for:
- Bootstrapping the KivyMD app
- Registering all screens with the ScreenManager
- Wiring shared services (database, storage) that screens depend on
- Handling Android lifecycle events (pause/resume, back button)
"""

import os

from kivy.core.window import Window
from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, NoTransition
from kivymd.app import MDApp

from database.database import DocumentDatabase
from storage.manager import StorageManager
from storage.preferences import AppPreferences

from ui.home import HomeScreen
from ui.scanner import ScannerScreen
from ui.preview import PreviewScreen
from ui.crop import CropScreen
from ui.editor import EditorScreen
from ui.documents import DocumentsScreen
from ui.settings import SettingsScreen

APP_NAME = "Document Scanner"
KV_DIR = os.path.join(os.path.dirname(__file__), "ui", "kv")


class ScannerApp(MDApp):
    """Root application object.

    Holds references to long-lived services (database, storage) so that
    any screen can reach them via `MDApp.get_running_app()` without each
    screen re-instantiating its own connection.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.title = APP_NAME
        self.icon = os.path.join("assets", "icons", "app_icon.png")

        # Shared services - single instances for the app's lifetime.
        self.storage = StorageManager(app_name="CamScannerPython")
        self.db = DocumentDatabase(
            db_path=self.storage.get_database_path()
        )
        self.prefs = AppPreferences(self.storage.root)

        # Holds pages (image paths) for a scan session in progress.
        # ui.scanner / ui.editor read and mutate this list directly.
        self.active_session_pages = []
        # Cross-screen handoff values, set by whichever screen navigates
        # away and read by whichever screen it navigates to.
        self.latest_capture_path = None
        self.latest_raw_path = None  # pre-perspective-correction photo, for the crop editor
        self.crop_source_path = None
        self.selected_document_id = None
        self.editing_document_id = None  # set when re-opening a saved document (step 10)

    def build(self):
        self.theme_cls.theme_style = self.prefs.get("theme_style")
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.accent_palette = "Amber"

        self._load_kv_files()

        self.screen_manager = ScreenManager(transition=NoTransition())

        self.screen_manager.add_widget(HomeScreen(name="home"))
        self.screen_manager.add_widget(ScannerScreen(name="scanner"))
        self.screen_manager.add_widget(PreviewScreen(name="preview"))
        self.screen_manager.add_widget(CropScreen(name="crop"))
        self.screen_manager.add_widget(EditorScreen(name="editor"))
        self.screen_manager.add_widget(DocumentsScreen(name="documents"))
        self.screen_manager.add_widget(SettingsScreen(name="settings"))

        return self.screen_manager

    def _load_kv_files(self):
        """Load every .kv file under ui/kv/ before screens are instantiated.

        Screens reference widget ids defined in these files, so this must
        run before add_widget() calls in build().
        """
        if not os.path.isdir(KV_DIR):
            return
        for filename in sorted(os.listdir(KV_DIR)):
            if filename.endswith(".kv"):
                Builder.load_file(os.path.join(KV_DIR, filename))

    def on_start(self):
        # Warm up the documents list so DocumentsScreen has data the
        # instant the user navigates to it.
        self.db.initialize()

    def on_pause(self):
        # Returning True lets the app resume instead of being killed
        # when the user switches apps mid-scan (required on Android).
        return True

    def on_resume(self):
        pass

    def go_to(self, screen_name: str, **transition_kwargs):
        """Central navigation helper so screens don't reach into
        each other's internals to switch screens."""
        for key, value in transition_kwargs.items():
            setattr(self.screen_manager.transition, key, value)
        self.screen_manager.current = screen_name


if __name__ == "__main__":
    Window.softinput_mode = "below_target"
    ScannerApp().run()
