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
import time
import threading
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
from storage.app_version import APP_VERSION, APP_SCHEMA_VERSION, CHANGELOG, run_app_migrations

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
    "app_lock": ("ui.app_lock", "AppLockScreen", None, {}),
    "tools": ("ui.tools", "ToolsScreen", None, {}),
    "nid_intelligence_tool": (
        "ui.tool_workflows",
        "ToolWorkflowScreen",
        None,
        {"mode": "nid_intelligence"},
    ),
    "passport_mrz_tool": (
        "ui.tool_workflows",
        "ToolWorkflowScreen",
        None,
        {"mode": "passport_mrz"},
    ),
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
    "merge_pdf_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "merge_pdf"}),
    "image_to_pdf_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "image_to_pdf"}),
    "text_to_pdf_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "text_to_pdf"}),
    "to_word_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "to_word"}),
    "pdf_to_word_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "pdf_to_word"}),
    "to_excel_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "to_excel"}),
    "pdf_to_images_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "pdf_to_images"}),
    "pdf_long_image_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "pdf_long_image"}),
    "bg_remover_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "bg_remover"}),
    "image_resizer_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "image_resizer"}),
    "smart_erase_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "smart_erase"}),
    "split_pdf_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "split_pdf"}),
    "sign_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "sign"}),
    "watermark_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "watermark"}),
    "extract_pages_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "extract_pages"}),
    "reorder_pages_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "reorder_pages"}),
    "rotate_pdf_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "rotate_pdf"}),
    "lock_pdf_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "lock_pdf"}),
    "unlock_pdf_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "unlock_pdf"}),
    "remove_pages_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "remove_pages"}),
    "insert_pages_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "insert_pages"}),
    "page_numbers_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "page_numbers"}),
    "header_footer_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "header_footer"}),
    "pdf_metadata_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "pdf_metadata"}),
    "flatten_pdf_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "flatten_pdf"}),
    "compress_pdf_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "compress_pdf"}),
    "create_qr_tool": ("ui.advanced_tools", "AdvancedToolScreen", None, {"mode": "create_qr"}),
    "print_tool": ("ui.print_tool", "PrintToolScreen", None, {}),
    "ai_chat": ("ui.ai_chat", "AIChatScreen", None, {}),
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
        self.pending_capture_mode = None
        self.pending_scan_type = None
        self.pending_scanner_action = None
        self.ai_api_key = ""  # never persisted to disk

        self._exit_dialog = None
        self._lock_return_screen = "home"
        self._paused_at = None
        self._is_locked = False
        self._sensitive_content = False
        self._last_screen = "home"
        self._last_action = "app_created"
        self._last_health_report = None
        self._draft_autosave_event = None
        self._draft_autosave_generation = 0
        self._draft_autosave_lock = threading.Lock()
        self._loaded_kv = set()
        self._old_excepthook = sys.excepthook
        sys.excepthook = self._handle_uncaught_exception


    def refresh_localized_ui(self):
        """Rebuild top-level screens after an app-language change.

        This keeps the language switch immediate without forcing a process
        restart. Heavy scanner/editor screens stay untouched so active work is
        not discarded.
        """
        from kivy.clock import Clock

        def _apply(_dt):
            sm = getattr(self, "screen_manager", None)
            if sm is None:
                return
            # Recreate Home because it is eager and owns a bottom navigation bar.
            old_home = sm.get_screen("home") if sm.has_screen("home") else None
            if old_home is not None:
                sm.remove_widget(old_home)
            sm.add_widget(HomeScreen(name="home"))
            sm.current = "home"
            # These are lazy and will be rebuilt in the selected language.
            for name in ("documents", "tools", "settings"):
                if sm.has_screen(name):
                    screen = sm.get_screen(name)
                    sm.remove_widget(screen)
            self.record_action("ui_language_refreshed")

        Clock.schedule_once(_apply, 0)

    # ------------------------------------------------------------------
    # Crash reporting
    # ------------------------------------------------------------------

    @property
    def crash_report_path(self) -> str:
        return os.path.join(self.storage.root, "crash_report.txt")

    def _write_crash_report(self, title: str, exc=None, extra: str = ""):
        try:
            from storage.diagnostics import format_diagnostics
            diagnostics = format_diagnostics(
                BASE_DIR,
                last_screen=getattr(self, "_last_screen", ""),
                last_action=getattr(self, "_last_action", ""),
            )
            lines = [
                "=" * 72,
                "PYCAM CRASH REPORT",
                "=" * 72,
                f"Time: {datetime.now().isoformat(timespec='seconds')}",
                f"Stage: {title}",
                "",
                diagnostics,
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
            if self.prefs.get("auto_temp_cleanup"):
                self.storage.clear_temp()
        except Exception:
            pass

        try:
            self.db.initialize()
            retention = str(self.prefs.get("trash_retention") or "30")
            if retention != "never":
                self.db.purge_trash_older_than(int(retention))
        except Exception as exc:
            # Database failure should not kill the process during startup.
            self._write_crash_report("database_initialize", exc=exc)

        # Apply non-destructive app-level migrations after the DB is available.
        try:
            applied = run_app_migrations(self)
            if applied:
                self.record_action("app_migrations:" + ",".join(map(str, applied)))
        except Exception as exc:
            self._write_crash_report("app_migrations", exc=exc)

        # Show release notes only once for each installed app version.
        try:
            previous_version = str(self.prefs.get("last_seen_version") or "")
            if previous_version != APP_VERSION:
                from kivy.clock import Clock

                def _show_release_notes(_dt):
                    dialog = MDDialog(
                        title=f"Pycam {APP_VERSION}",
                        text="What’s new:\n\n" + "\n".join(f"• {item}" for item in CHANGELOG),
                        buttons=[MDFlatButton(text="OK", on_release=lambda *_: dialog.dismiss())],
                    )
                    dialog.open()
                    self.prefs.set("last_seen_version", APP_VERSION)

                Clock.schedule_once(_show_release_notes, 0.8)
        except Exception:
            pass

        # Run a non-destructive startup health check after the database is ready.
        # It must never block app launch or turn an optional feature problem into
        # a startup crash. The full/deep scan remains user-triggered in Settings.
        try:
            from kivy.clock import Clock

            def _startup_health(_dt):
                try:
                    from storage.health_check import run_health_check
                    report = run_health_check(self, BASE_DIR, deep=False, persist=True)
                    self._last_health_report = report
                    if not report.get("ok"):
                        self.record_action(
                            f"health_check:errors={report.get('errors', 0)};warnings={report.get('warnings', 0)}"
                        )
                except Exception as health_exc:
                    self._write_crash_report("startup_health_check", exc=health_exc)

            Clock.schedule_once(_startup_health, 0.35)
        except Exception:
            pass

        # Restore an unfinished scan draft after TEMP cleanup. Draft pages live
        # in their own persistent directory, so a normal startup cleanup cannot
        # erase them. Home exposes a Resume action rather than forcing navigation.
        try:
            draft_pages, draft_document_id = self.storage.load_session_draft()
            if draft_pages:
                if draft_document_id is not None and not self.db.get_document(draft_document_id):
                    draft_document_id = None
                self.active_session_pages = list(draft_pages)
                self.editing_document_id = draft_document_id
                self.latest_capture_path = draft_pages[-1]
        except Exception as exc:
            self._write_crash_report("load_session_draft", exc=exc)

        try:
            from storage.privacy import set_secure_window
            set_secure_window(bool(self.prefs.get("block_screenshots") and self.prefs.get("app_lock_enabled")))
        except Exception:
            pass

        Window.bind(on_keyboard=self._on_keyboard)

        # App lock is evaluated only after Home has been built, so startup
        # failures in optional screens cannot block the launcher.
        try:
            if self.prefs.get("app_lock_enabled"):
                from kivy.clock import Clock
                Clock.schedule_once(lambda dt: self.lock_app(force=True), 0)
        except Exception:
            pass

    def on_pause(self):
        self.record_action("app_paused")
        self._paused_at = time.monotonic()
        try:
            self.persist_session_draft()
        except Exception:
            pass
        return True

    def on_stop(self):
        try:
            self.persist_session_draft()
        except Exception:
            pass

    def on_resume(self):
        self.record_action("app_resumed")
        try:
            if not self.prefs.get("app_lock_enabled"):
                return
            timeout = self.prefs.get("app_lock_timeout") or "immediate"
            seconds = {"immediate": 0, "1min": 60, "5min": 300, "15min": 900}.get(timeout, 0)
            elapsed = 0 if self._paused_at is None else max(0, time.monotonic() - self._paused_at)
            if elapsed >= seconds:
                self.lock_app(force=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Unfinished scan persistence
    # ------------------------------------------------------------------

    def persist_session_draft(self):
        if not self.active_session_pages:
            self.storage.clear_session_draft()
            return []
        return self.storage.save_session_draft(
            self.active_session_pages,
            editing_document_id=self.editing_document_id,
        )

    def clear_session_draft(self):
        self._draft_autosave_generation += 1
        event = self._draft_autosave_event
        self._draft_autosave_event = None
        try:
            if event is not None:
                event.cancel()
        except Exception:
            pass
        self.storage.clear_session_draft()

    def schedule_session_autosave(self, reason="edit", delay=0.75):
        """Debounce unfinished-session persistence after destructive edits.

        Protected documents are deliberately excluded: their editable pages are
        temporary plaintext materializations of encrypted vault content. Writing
        those pages into the normal draft directory would weaken at-rest privacy.
        The original encrypted document remains intact until Save is confirmed.
        """
        if not self.active_session_pages:
            return False
        if self.editing_document_id is not None:
            try:
                doc = self.db.get_document(self.editing_document_id) or {}
                if doc.get("protected"):
                    self.record_action("autosave_skipped:protected_document")
                    return False
            except Exception:
                return False

        self._draft_autosave_generation += 1
        generation = self._draft_autosave_generation
        try:
            if self._draft_autosave_event is not None:
                self._draft_autosave_event.cancel()
        except Exception:
            pass

        def _launch(_dt):
            pages = list(self.active_session_pages)
            document_id = self.editing_document_id
            self._draft_autosave_event = None
            threading.Thread(
                target=self._autosave_session_worker,
                args=(generation, pages, document_id, str(reason or "edit")),
                daemon=True,
            ).start()

        from kivy.clock import Clock
        self._draft_autosave_event = Clock.schedule_once(_launch, max(0.05, float(delay)))
        return True

    def _autosave_session_worker(self, generation, pages, document_id, reason):
        if generation != self._draft_autosave_generation:
            return
        try:
            with self._draft_autosave_lock:
                if generation != self._draft_autosave_generation:
                    return
                self.storage.save_session_draft(
                    pages, editing_document_id=document_id, reason=reason
                )
            self.record_action(f"session_autosaved:{reason}")
        except Exception as exc:
            self._write_crash_report("session_autosave", exc=exc, extra=f"Reason: {reason}")

    # ------------------------------------------------------------------
    # Privacy lock
    # ------------------------------------------------------------------
    def set_sensitive_content(self, enabled: bool):
        self._sensitive_content = bool(enabled)
        try:
            from storage.privacy import set_secure_window
            secure = bool(self.prefs.get("block_screenshots")) and (
                self._sensitive_content or self._is_locked or bool(self.prefs.get("app_lock_enabled"))
            )
            set_secure_window(secure)
        except Exception:
            pass


    def lock_app(self, force=False):
        from storage.security import has_pin
        if not has_pin(self.prefs):
            self._is_locked = False
            self.prefs.set("app_lock_enabled", False)
            return
        if not force and not self.prefs.get("app_lock_enabled"):
            return
        current = getattr(self.screen_manager, "current", "home")
        if current != "app_lock":
            self._lock_return_screen = current or "home"
        self._is_locked = True
        self.set_sensitive_content(self._sensitive_content)
        if not self.screen_manager.has_screen("app_lock"):
            self._create_lazy_screen("app_lock")
        if self.screen_manager.has_screen("app_lock"):
            self.screen_manager.current = "app_lock"

    def unlock_app(self):
        self._is_locked = False
        self.set_sensitive_content(self._sensitive_content)
        target = self._lock_return_screen or "home"
        if target == "app_lock" or not self.screen_manager.has_screen(target):
            target = "home"
        self.screen_manager.current = target

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def record_action(self, action: str):
        """Record only a short action label; never document content/path."""
        self._last_action = str(action or "")[:160]

    def go_to(self, screen_name: str, **transition_kwargs):
        current = getattr(self.screen_manager, "current", "")
        self.record_action(f"navigate:{current or 'unknown'}->{screen_name}")
        if current in {"scanner", "preview", "crop", "editor", "photo_picker"} and self.active_session_pages:
            try:
                self.persist_session_draft()
            except Exception:
                pass
        if current == "editor" and screen_name != "editor" and self._sensitive_content:
            self.set_sensitive_content(False)
        if self._is_locked and screen_name != "app_lock":
            screen_name = "app_lock"
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
        self._last_screen = screen_name

    # ------------------------------------------------------------------
    # Back / exit
    # ------------------------------------------------------------------

    def _on_keyboard(self, window, key, scancode, codepoint, modifiers):
        if key not in (27, 1001):
            return False

        if self._exit_dialog is not None:
            return True

        if self.screen_manager.current == "app_lock":
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
