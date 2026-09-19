"""Expanded Settings screen wired to real scanner/export/storage behaviour."""

import os
from kivy.core.clipboard import Clipboard
from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.selectioncontrol import MDSwitch
from kivymd.uix.toolbar import MDTopAppBar
from kivymd.uix.textfield import MDTextField

from storage.file_picker import FilePicker
from storage.localization import tr
from storage.accessibility import label_widget, ensure_touch_target

from ui.navigation import BottomNavigationBar

ACTIVE = (0.05, 0.52, 0.46, 1)
INACTIVE = (0.25, 0.29, 0.35, 1)


class ChoiceRow(MDBoxLayout):
    def __init__(self, label, options, current_value, on_choose, **kwargs):
        super().__init__(orientation="vertical", size_hint_y=None, height=dp(76),
                         padding=(dp(16), dp(3)), **kwargs)
        self.add_widget(MDLabel(text=label, theme_text_color="Secondary", font_style="Caption"))
        row = MDBoxLayout(orientation="horizontal", spacing=dp(2))
        self._buttons = {}
        for value, text in options:
            btn = MDFlatButton(
                text=text,
                theme_text_color="Custom",
                text_color=ACTIVE if value == current_value else INACTIVE,
                on_release=lambda inst, v=value: self._choose(v, on_choose),
            )
            self._buttons[value] = btn
            row.add_widget(btn)
        self.add_widget(row)

    def _choose(self, value, callback):
        self.sync(value)
        callback(value)

    def sync(self, value):
        for key, btn in self._buttons.items():
            btn.text_color = ACTIVE if key == value else INACTIVE


class SettingsScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        app = MDApp.get_running_app()
        self.language = app.prefs.get("app_language") if getattr(app, "prefs", None) else "en"
        self._t = lambda key, default=None: tr(key, self.language, default)
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(MDTopAppBar(title=self._t("settings", "Settings"), elevation=0))

        scroll = ScrollView(do_scroll_x=False)
        self.body = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(4),
                                padding=(0, dp(6), 0, dp(20)))
        scroll.add_widget(self.body)
        root.add_widget(scroll)
        root.add_widget(BottomNavigationBar(selected="settings"))
        self.add_widget(root)

        self._section(self._t("scanner", "SCANNER"))
        self.auto_switch = self._switch(self._t("auto_capture", "Auto capture"), "auto_capture")
        self.auto_crop_switch = self._switch(self._t("auto_crop", "Auto crop after capture"), "auto_crop")
        self.sensitivity_row = self._choice(self._t("edge_sensitivity", "Edge detection sensitivity"),
                                            [("low", "LOW"), ("balanced", "NORMAL"), ("high", "HIGH")],
                                            "edge_sensitivity")
        self.delay_row = self._choice(self._t("capture_delay", "Capture delay"),
                                      [("fast", "FAST"), ("normal", "NORMAL"), ("slow", "SLOW")],
                                      "capture_delay")
        self.hd_switch = self._switch(self._t("high_resolution", "High resolution scan"), "high_resolution")
        self.enhance_switch = self._switch(self._t("auto_enhance", "Auto enhance"), "auto_enhance")
        self.sound_switch = self._switch(self._t("shutter_sound", "Shutter sound"), "shutter_sound")
        self.vibration_switch = self._switch(self._t("vibration", "Vibration"), "vibration")

        self._section(self._t("export", "EXPORT"))
        self.export_row = self._choice(self._t("default_format", "Default format"),
                                       [("pdf", "PDF"), ("jpg", "JPG"), ("png", "PNG")],
                                       "export_format")
        self.page_row = self._choice(self._t("default_page", "Default PDF page"),
                                     [("auto", "AUTO"), ("a4", "A4"), ("letter", "LETTER"), ("legal", "LEGAL")],
                                     "pdf_page_size")
        self.margin_row = self._choice(self._t("default_margin", "Default margin"),
                                       [("none", "NONE"), ("small", "SMALL"), ("normal", "NORMAL"), ("large", "LARGE")],
                                       "pdf_margin")
        self.quality_row = self._choice(self._t("default_quality", "Default quality"),
                                        [("high", "HIGH"), ("balanced", "NORMAL"), ("small", "SMALL")],
                                        "export_quality")
        self.searchable_switch = self._switch(self._t("searchable_pdf", "Searchable PDF by default"), "searchable_pdf")
        self.export_destination_row = self._choice(
            self._t("save_exports", "Save exported files"),
            [("app", "APP"), ("downloads", "DOWNLOADS"), ("custom", "CUSTOM")],
            "export_destination",
        )
        export_folder_controls = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52),
                                              padding=(dp(12), 0), spacing=dp(8))
        self.export_folder_label = MDLabel(text=self._t("custom_folder_none", "Custom folder: not selected"), size_hint_x=.62,
                                           theme_text_color="Secondary")
        export_folder_controls.add_widget(self.export_folder_label)
        export_folder_controls.add_widget(MDFlatButton(text=self._t("choose", "CHOOSE"), on_release=lambda *_: self._choose_export_folder()))
        export_folder_controls.add_widget(MDFlatButton(text=self._t("reset", "RESET"), on_release=lambda *_: self._reset_export_folder()))
        self.body.add_widget(export_folder_controls)

        self._section(self._t("ocr", "OCR"))
        self.ocr_row = self._choice(self._t("default_ocr", "Default OCR language"),
                                    [("english", "ENGLISH"), ("bengali", "BENGALI"), ("mixed", "EN + বাংলা")],
                                    "ocr_language")
        self.auto_ocr_switch = self._switch(self._t("auto_ocr", "Auto OCR after save"), "auto_ocr")
        self.keep_ocr_switch = self._switch(self._t("keep_ocr", "Keep OCR text"), "keep_ocr_text")

        self._section(self._t("app_privacy", "APP & PRIVACY"))
        self.language_row = self._choice(
            self._t("app_language", "App language"),
            [("en", "ENGLISH"), ("bn", "বাংলা")],
            "app_language",
        )
        self.theme_switch = self._switch(self._t("dark_theme", "Dark theme"), "_theme")
        self.analytics_switch = self._switch(self._t("anonymous_analytics", "Anonymous analytics"), "analytics_enabled")
        self.cleanup_switch = self._switch(self._t("clean_temp", "Clean temporary files on startup"), "auto_temp_cleanup")
        self.screenshot_switch = self._switch(self._t("block_screenshots", "Block screenshots for locked/protected content"), "block_screenshots")
        self.screenshot_switch.bind(active=lambda *_: self._apply_screenshot_policy())
        self.trash_retention_row = self._choice(
            self._t("trash_auto_delete", "Trash auto-delete"),
            [("never", "NEVER"), ("7", "7 DAYS"), ("30", "30 DAYS"), ("90", "90 DAYS")],
            "trash_retention",
        )

        self._syncing_security = False
        lock_row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52), padding=(dp(16), 0))
        lock_row.add_widget(MDLabel(text=self._t("app_lock", "App lock / PIN")))
        self.app_lock_switch = MDSwitch(active=False)
        self.app_lock_switch.bind(active=self._on_app_lock_toggle)
        lock_row.add_widget(self.app_lock_switch)
        self.body.add_widget(lock_row)

        self._syncing_biometric = False
        biometric_row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52), padding=(dp(16), 0))
        biometric_row.add_widget(MDLabel(text=self._t("biometric_unlock", "Biometric unlock")))
        self.biometric_switch = MDSwitch(active=False)
        self.biometric_switch.bind(active=self._on_biometric_toggle)
        biometric_row.add_widget(self.biometric_switch)
        self.body.add_widget(biometric_row)

        self.lock_timeout_row = self._choice(
            self._t("lock_background", "Lock after background"),
            [("immediate", "NOW"), ("1min", "1 MIN"), ("5min", "5 MIN"), ("15min", "15 MIN")],
            "app_lock_timeout",
        )
        pin_buttons = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52), padding=(dp(12), 0), spacing=dp(8))
        pin_buttons.add_widget(MDRaisedButton(text=self._t("set_pin", "SET / CHANGE PIN"), on_release=lambda *_: self._change_pin()))
        pin_buttons.add_widget(MDFlatButton(text=self._t("remove_pin", "REMOVE PIN"), on_release=lambda *_: self._remove_pin()))
        self.body.add_widget(pin_buttons)

        self.cache_label = MDLabel(text="Cache: calculating…", size_hint_y=None, height=dp(38),
                                   padding=(dp(16), 0), theme_text_color="Secondary")
        self.body.add_widget(self.cache_label)
        buttons = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52),
                              padding=(dp(12), 0), spacing=dp(8))
        buttons.add_widget(MDRaisedButton(text=self._t("clear_cache", "CLEAR CACHE"), on_release=lambda *_: self._clear_cache()))
        buttons.add_widget(MDFlatButton(text=self._t("crash_report", "CRASH REPORT"), on_release=lambda *_: self._show_crash_report()))
        self.body.add_widget(buttons)
        diag_buttons = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52),
                                   padding=(dp(12), 0), spacing=dp(8))
        diag_buttons.add_widget(MDFlatButton(text=self._t("device_info", "DEVICE INFO"), on_release=lambda *_: self._show_device_info()))
        diag_buttons.add_widget(MDFlatButton(text=self._t("share_report", "SHARE REPORT"), on_release=lambda *_: self._share_crash_report()))
        self.body.add_widget(diag_buttons)

        health_buttons = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52),
                                     padding=(dp(12), 0), spacing=dp(8))
        health_buttons.add_widget(MDRaisedButton(text=self._t("run_health", "RUN HEALTH CHECK"), on_release=lambda *_: self._run_health_check()))
        health_buttons.add_widget(MDFlatButton(text=self._t("last_health", "LAST HEALTH REPORT"), on_release=lambda *_: self._show_health_report()))
        self.body.add_widget(health_buttons)

        self._section(self._t("about", "ABOUT"))
        about_buttons = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52),
                                    padding=(dp(12), 0), spacing=dp(8))
        about_buttons.add_widget(MDRaisedButton(text=self._t("app_info", "APP INFO"), on_release=lambda *_: self._show_app_info()))
        about_buttons.add_widget(MDFlatButton(text=self._t("whats_new", "WHAT'S NEW"), on_release=lambda *_: self._show_changelog()))
        self.body.add_widget(about_buttons)

        self._section("BACKUP & FILE NAMING")
        naming = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(56), padding=(dp(16), 0), spacing=dp(8))
        naming.add_widget(MDLabel(text=self._t("filename_template", "Filename template"), size_hint_x=.42))
        self.filename_field = MDTextField(
            text="Scan_{date}_{time}",
            hint_text="Scan_{date}_{time}",
            helper_text="Use {date}, {time}, or {datetime}",
            helper_text_mode="on_focus",
            size_hint_x=.58,
        )
        self.filename_field.bind(on_text_validate=lambda inst: self._save_filename_template(inst.text))
        naming.add_widget(self.filename_field)
        self.body.add_widget(naming)

        backup_buttons = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(54),
                                     padding=(dp(12), 0), spacing=dp(8))
        backup_buttons.add_widget(MDRaisedButton(text=self._t("export_backup", "EXPORT BACKUP"), on_release=lambda *_: self._export_backup()))
        backup_buttons.add_widget(MDFlatButton(text=self._t("restore_backup", "RESTORE BACKUP"), on_release=lambda *_: self._pick_restore_backup()))
        self.body.add_widget(backup_buttons)
        vault_buttons = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(54),
                                    padding=(dp(12), 0), spacing=dp(8))
        vault_buttons.add_widget(MDFlatButton(text=self._t("check_vault", "CHECK PRIVATE VAULT"), on_release=lambda *_: self._check_private_vault()))
        vault_buttons.add_widget(MDFlatButton(text=self._t("repair_paths", "REPAIR PATHS"), on_release=lambda *_: self._repair_private_vault()))
        self.body.add_widget(vault_buttons)
        self._backup_picker = FilePicker()

    def _section(self, title):
        self.body.add_widget(MDLabel(text=title, bold=True, size_hint_y=None, height=dp(38),
                                     padding=(dp(16), 0), theme_text_color="Primary"))

    def _switch(self, label, key):
        row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52), padding=(dp(16), 0))
        row.add_widget(MDLabel(text=label))
        switch = MDSwitch(active=False)
        if key == "_theme":
            switch.bind(active=self._on_theme)
        else:
            switch.bind(active=lambda inst, value, k=key: MDApp.get_running_app().prefs.set(k, bool(value)))
        label_widget(switch, label, "switch")
        ensure_touch_target(switch)
        row.add_widget(switch)
        self.body.add_widget(row)
        return switch

    def _choice(self, label, options, key):
        row = ChoiceRow(label, options, options[0][0], lambda value, k=key: self._set_choice(k, value))
        self.body.add_widget(row)
        return row


    def _set_choice(self, key, value):
        app = MDApp.get_running_app()
        app.prefs.set(key, value)
        if key == "app_language":
            self.language = value
            if hasattr(app, "refresh_localized_ui"):
                app.refresh_localized_ui()

    def on_pre_enter(self, *args):
        app = MDApp.get_running_app()
        pairs = [
            (self.auto_switch, "auto_capture"), (self.auto_crop_switch, "auto_crop"),
            (self.hd_switch, "high_resolution"), (self.enhance_switch, "auto_enhance"),
            (self.sound_switch, "shutter_sound"), (self.vibration_switch, "vibration"),
            (self.searchable_switch, "searchable_pdf"), (self.auto_ocr_switch, "auto_ocr"),
            (self.keep_ocr_switch, "keep_ocr_text"), (self.analytics_switch, "analytics_enabled"),
            (self.cleanup_switch, "auto_temp_cleanup"), (self.screenshot_switch, "block_screenshots"),
        ]
        for widget, key in pairs:
            widget.active = bool(app.prefs.get(key))
        self.theme_switch.active = app.prefs.get("theme_style") == "Dark"
        self._syncing_security = True
        self.app_lock_switch.active = bool(app.prefs.get("app_lock_enabled"))
        self._syncing_security = False
        self._syncing_biometric = True
        self.biometric_switch.active = bool(app.prefs.get("biometric_unlock"))
        self._syncing_biometric = False
        for row, key in [
            (self.sensitivity_row, "edge_sensitivity"), (self.delay_row, "capture_delay"),
            (self.export_row, "export_format"), (self.page_row, "pdf_page_size"),
            (self.margin_row, "pdf_margin"), (self.quality_row, "export_quality"),
            (self.export_destination_row, "export_destination"),
            (self.ocr_row, "ocr_language"), (self.lock_timeout_row, "app_lock_timeout"),
            (self.trash_retention_row, "trash_retention"), (self.language_row, "app_language")]:
            row.sync(app.prefs.get(key))
        self.filename_field.text = app.prefs.get("filename_template") or "Scan_{date}_{time}"
        label = app.prefs.get("export_tree_label") or "not selected"
        self.export_folder_label.text = f"Custom folder: {label}"
        self._refresh_cache_label()

    def _on_app_lock_toggle(self, _instance, value):
        if getattr(self, "_syncing_security", False):
            return
        app = MDApp.get_running_app()
        from storage.security import has_pin
        if value:
            if not has_pin(app.prefs):
                self._syncing_security = True
                self.app_lock_switch.active = False
                self._syncing_security = False
                self._prompt_new_pin(enable_after=True)
                return
            app.prefs.set("app_lock_enabled", True)
        else:
            if not has_pin(app.prefs):
                app.prefs.set("app_lock_enabled", False)
                return
            from ui.app_lock import request_pin
            self._syncing_security = True
            self.app_lock_switch.active = True
            self._syncing_security = False
            def disable():
                app.prefs.set("app_lock_enabled", False)
                self._syncing_security = True
                self.app_lock_switch.active = False
                self._syncing_security = False
            request_pin("Disable app lock", disable)

    def _on_biometric_toggle(self, _instance, value):
        if getattr(self, "_syncing_biometric", False):
            return
        app = MDApp.get_running_app()
        from storage.security import has_pin

        if not value:
            app.prefs.set("biometric_unlock", False)
            return

        if not has_pin(app.prefs):
            self._syncing_biometric = True
            self.biometric_switch.active = False
            self._syncing_biometric = False
            self._message("Biometric unlock", "Create an app PIN first. The PIN remains the fallback unlock method.")
            return

        try:
            from storage.biometric import availability, authenticate
            ok, message = availability()
        except Exception as exc:
            ok, message = False, str(exc)
        if not ok:
            self._syncing_biometric = True
            self.biometric_switch.active = False
            self._syncing_biometric = False
            app.prefs.set("biometric_unlock", False)
            self._message("Biometric unavailable", message)
            return

        # Verify biometric once before enabling it. PIN is always retained as fallback.
        self._syncing_biometric = True
        self.biometric_switch.active = False
        self._syncing_biometric = False

        def enabled():
            app.prefs.set("biometric_unlock", True)
            self._syncing_biometric = True
            self.biometric_switch.active = True
            self._syncing_biometric = False
            self._message("Biometric unlock", "Biometric unlock is enabled. Your PIN remains available as fallback.")

        def failed(msg):
            app.prefs.set("biometric_unlock", False)
            self._syncing_biometric = True
            self.biometric_switch.active = False
            self._syncing_biometric = False
            if msg and "Use your PIN" not in str(msg):
                self._message("Biometric unlock", str(msg))

        authenticate("Enable biometric unlock", enabled, failed, subtitle="Confirm your fingerprint or face")

    def _prompt_new_pin(self, enable_after=False):
        app = MDApp.get_running_app()
        box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8))
        first = MDTextField(hint_text="New PIN (4–8 digits)", password=True, input_filter="int", max_text_length=8)
        second = MDTextField(hint_text="Confirm PIN", password=True, input_filter="int", max_text_length=8)
        box.add_widget(first); box.add_widget(second)
        def save(*_):
            from storage.security import set_pin, is_valid_pin_format
            if not is_valid_pin_format(first.text or ""):
                second.helper_text = "PIN must contain 4–8 digits"; second.helper_text_mode = "persistent"
                return
            if first.text != second.text:
                second.text = ""; second.hint_text = "PINs do not match"; second.focus = True
                return
            set_pin(app.prefs, first.text)
            if enable_after:
                app.prefs.set("app_lock_enabled", True)
                self._syncing_security = True
                self.app_lock_switch.active = True
                self._syncing_security = False
            dialog.dismiss()
            self._message("PIN saved", "Your PIN is stored as a salted security hash, not plaintext.")
        dialog = MDDialog(
            title="Create app PIN", type="custom", content_cls=box,
            buttons=[MDFlatButton(text="CANCEL", on_release=lambda *_: dialog.dismiss()), MDRaisedButton(text="SAVE", on_release=save)],
        )
        dialog.open(); first.focus = True

    def _change_pin(self):
        app = MDApp.get_running_app()
        from storage.security import has_pin
        if not has_pin(app.prefs):
            self._prompt_new_pin(enable_after=False)
            return
        from ui.app_lock import request_pin
        request_pin("Verify current PIN", lambda: self._prompt_new_pin(enable_after=False))

    def _remove_pin(self):
        app = MDApp.get_running_app()
        from storage.security import has_pin, clear_pin
        if not has_pin(app.prefs):
            self._message("App PIN", "No PIN is currently configured.")
            return
        from ui.app_lock import request_pin
        def remove():
            try:
                from storage.private_vault import unprotect_document
                protected_docs = [
                    d for d in app.db.list_documents(include_deleted=True)
                    if d.get("protected")
                ]
                for doc in protected_docs:
                    unprotect_document(app, doc["id"])
            except Exception as exc:
                self._message(
                    "PIN not removed",
                    "A protected document could not be decrypted. Your PIN and protection were kept.\n\n" + str(exc),
                )
                return
            clear_pin(app.prefs)
            app.prefs.set("biometric_unlock", False)
            self._syncing_biometric = True
            self.biometric_switch.active = False
            self._syncing_biometric = False
            self._syncing_security = True
            self.app_lock_switch.active = False
            self._syncing_security = False
            self._message("PIN removed", "App lock and document protection are now disabled until a new PIN is created.")
        request_pin("Remove app PIN", remove)

    def _apply_screenshot_policy(self):
        app = MDApp.get_running_app()
        try:
            app.set_sensitive_content(getattr(app, "_sensitive_content", False))
        except Exception:
            pass

    def _on_theme(self, _instance, value):
        app = MDApp.get_running_app()
        style = "Dark" if value else "Light"
        app.prefs.set("theme_style", style)
        app.theme_cls.theme_style = style

    @staticmethod
    def _pretty_size(value):
        n = float(value)
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024.0 or unit == "GB":
                return f"{n:.1f} {unit}"
            n /= 1024.0

    def _refresh_cache_label(self):
        app = MDApp.get_running_app()
        self.cache_label.text = "Temporary cache: " + self._pretty_size(app.storage.get_temp_size_bytes())

    def _clear_cache(self):
        app = MDApp.get_running_app()
        app.storage.clear_temp()
        self._refresh_cache_label()
        self._message("Cache cleared", "Temporary files were removed.")


    def _choose_export_folder(self):
        app = MDApp.get_running_app()
        try:
            from storage.export_destination import choose_custom_export_folder

            def chosen(uri, label):
                app.prefs.set("export_tree_uri", uri)
                app.prefs.set("export_tree_label", label or "Custom folder")
                app.prefs.set("export_destination", "custom")
                self.export_destination_row.sync("custom")
                self.export_folder_label.text = f"Custom folder: {label or 'selected'}"
                self._message("Export folder", f"Future exports will also be copied to:\n{label or 'the selected folder'}")

            choose_custom_export_folder(chosen, lambda msg: self._message("Export folder", str(msg)))
        except Exception as exc:
            self._message("Export folder", str(exc))

    def _reset_export_folder(self):
        app = MDApp.get_running_app()
        app.prefs.set("export_tree_uri", "")
        app.prefs.set("export_tree_label", "")
        app.prefs.set("export_destination", "app")
        self.export_destination_row.sync("app")
        self.export_folder_label.text = "Custom folder: not selected"
        self._message("Export folder", "Custom folder cleared. Exports will stay in app storage until you choose another destination.")

    def _save_filename_template(self, value):
        value = (value or "").strip() or "Scan_{date}_{time}"
        # Validate format tokens now so saving a document cannot fail later.
        try:
            value.format(date="2026-01-01", time="12-30", datetime="2026-01-01_12-30")
        except Exception:
            self._message("Filename template", "Use only {date}, {time}, and {datetime} placeholders.")
            self.filename_field.text = MDApp.get_running_app().prefs.get("filename_template") or "Scan_{date}_{time}"
            return
        MDApp.get_running_app().prefs.set("filename_template", value)

    def _export_backup(self):
        app = MDApp.get_running_app()
        try:
            from storage.backup import create_backup, validate_backup
            path = create_backup(app.storage)
            info = validate_backup(path, verify_checksums=True)
            try:
                external = app.storage.publish_export(path, app.prefs)
                external_line = "" if external == path else f"\nExternal copy: {external}"
            except Exception as publish_exc:
                external_line = f"\nExternal save failed: {publish_exc}"
            self._message(
                "Backup created",
                f"Backup saved to:\n{path}{external_line}\n\nVerified files: {info.get('verified_entries', 0)}\nEncrypted vault files: {info.get('encrypted_vault_files', 0)}",
            )
        except Exception as exc:
            self._message("Backup failed", str(exc))

    def _pick_restore_backup(self):
        self._backup_picker.choose_zip(self._confirm_restore_backup, self._restore_error)

    def _restore_error(self, message):
        self._message("Restore backup", str(message))

    def _confirm_restore_backup(self, path):
        dialog = MDDialog(
            title="Restore backup?",
            text="Current documents and preferences will be replaced by the selected backup. This cannot be undone unless you export a backup first.",
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *_: dialog.dismiss()),
                MDFlatButton(text="RESTORE", on_release=lambda *_: self._restore_backup(dialog, path)),
            ],
        )
        dialog.open()

    def _restore_backup(self, dialog, path):
        dialog.dismiss()
        app = MDApp.get_running_app()
        try:
            from storage.backup import restore_backup
            restore_backup(path, app.storage, app.db)
            # Re-read restored preferences from disk.
            from storage.preferences import AppPreferences
            app.prefs = AppPreferences(app.storage.root)
            self._message("Restore complete", "Documents and settings were restored. Reopen screens to refresh their data.")
        except Exception as exc:
            try:
                app.db.initialize()
            except Exception:
                pass
            self._message("Restore failed", str(exc))


    def _check_private_vault(self):
        app = MDApp.get_running_app()
        try:
            from storage.private_vault import scan_vault_integrity
            report = scan_vault_integrity(app)
            issues = report.get("issues") or []
            orphaned = report.get("orphaned_files") or []
            if not issues:
                text = (
                    f"Private vault is healthy.\n\n"
                    f"Protected documents: {report.get('protected_documents', 0)}\n"
                    f"Verified pages: {report.get('healthy_pages', 0)}/{report.get('checked_pages', 0)}\n"
                    f"Orphaned encrypted files: {len(orphaned)}\n"
                    f"Key fingerprint: {report.get('key_fingerprint') or 'not created'}"
                )
            else:
                preview = "\n".join(f"• Doc {i.get('document_id')}: {i.get('message')}" for i in issues[:8])
                text = (
                    f"Vault issues found: {len(issues)}\n"
                    f"Verified pages: {report.get('healthy_pages', 0)}/{report.get('checked_pages', 0)}\n"
                    f"Orphaned files: {len(orphaned)}\n\n{preview}"
                )
            self._message("Private vault check", text)
        except Exception as exc:
            self._message("Private vault check failed", str(exc))

    def _repair_private_vault(self):
        app = MDApp.get_running_app()
        try:
            from storage.private_vault import repair_missing_vault_paths, scan_vault_integrity
            result = repair_missing_vault_paths(app)
            report = scan_vault_integrity(app)
            self._message(
                "Private vault repair",
                f"Repaired documents: {len(result.get('repaired', []))}\n"
                f"Skipped: {len(result.get('skipped', []))}\n"
                f"Remaining issues: {len(report.get('issues') or [])}",
            )
        except Exception as exc:
            self._message("Private vault repair failed", str(exc))

    def _run_health_check(self):
        app = MDApp.get_running_app()
        try:
            from storage.health_check import run_health_check, format_health_report
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            report = run_health_check(app, base_dir, deep=True, persist=True)
            app._last_health_report = report
            text = format_health_report(report)
            preview = text[-6500:]
            dialog = MDDialog(
                title="Health check" if report.get("ok") else "Health check - needs attention",
                text=preview,
                buttons=[
                    MDFlatButton(text="COPY", on_release=lambda *_: Clipboard.copy(text)),
                    MDFlatButton(text="SHARE", on_release=lambda *_: self._share_text(text)),
                    MDFlatButton(text="CLOSE", on_release=lambda *_: dialog.dismiss()),
                ],
            )
            dialog.open()
        except Exception as exc:
            self._message("Health check failed", str(exc))

    def _show_health_report(self):
        app = MDApp.get_running_app()
        try:
            from storage.health_check import read_last_health_report, format_health_report
            report = read_last_health_report(app)
            if not report:
                self._message("Health report", "No health check has been saved yet.")
                return
            text = format_health_report(report)
            dialog = MDDialog(
                title="Last health report",
                text=text[-6500:],
                buttons=[
                    MDFlatButton(text="COPY", on_release=lambda *_: Clipboard.copy(text)),
                    MDFlatButton(text="SHARE", on_release=lambda *_: self._share_text(text)),
                    MDFlatButton(text="CLOSE", on_release=lambda *_: dialog.dismiss()),
                ],
            )
            dialog.open()
        except Exception as exc:
            self._message("Health report", str(exc))

    def _show_app_info(self):
        try:
            from storage.app_version import APP_VERSION, APP_SCHEMA_VERSION, BUILD_FLAVOR
            app = MDApp.get_running_app()
            text = (
                f"Pycam {APP_VERSION}\n"
                f"Build: {BUILD_FLAVOR}\n"
                f"App schema: {APP_SCHEMA_VERSION}\n"
                f"Database: {getattr(app.db, '_path', 'app storage')}\n"
                f"Export destination: {app.prefs.get('export_destination')}"
            )
            self._message("About Pycam", text)
        except Exception as exc:
            self._message("About Pycam", str(exc))

    def _show_changelog(self):
        try:
            from storage.app_version import APP_VERSION, CHANGELOG
            text = f"Pycam {APP_VERSION}\n\n" + "\n".join(f"• {item}" for item in CHANGELOG)
            self._message("What's new", text)
        except Exception as exc:
            self._message("What's new", str(exc))

    def _show_crash_report(self):
        app = MDApp.get_running_app()
        path = app.crash_report_path
        if not os.path.isfile(path):
            self._message("Crash report", "No crash report is currently saved.")
            return
        try:
            text = open(path, "r", encoding="utf-8", errors="replace").read()
        except OSError as exc:
            self._message("Crash report", str(exc)); return
        preview = text[-5000:]
        dialog = MDDialog(title="Crash report", text=preview,
                          buttons=[
                              MDFlatButton(text="COPY", on_release=lambda *_: Clipboard.copy(text)),
                              MDFlatButton(text="SHARE", on_release=lambda *_: self._share_text(text)),
                              MDFlatButton(text="CLEAR", on_release=lambda *_: self._clear_crash(dialog, path)),
                              MDFlatButton(text="CLOSE", on_release=lambda *_: dialog.dismiss()),
                          ])
        dialog.open()


    def _show_device_info(self):
        app = MDApp.get_running_app()
        try:
            from storage.diagnostics import format_diagnostics
            text = format_diagnostics(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                last_screen=getattr(app, "_last_screen", ""),
                last_action=getattr(app, "_last_action", ""),
            )
            self._message("Device & app info", text)
        except Exception as exc:
            self._message("Device & app info", str(exc))

    def _share_text(self, text):
        try:
            from storage.android_actions import share_text
            share_text("Pycam crash report", text)
        except Exception as exc:
            # Clipboard fallback keeps diagnostics usable outside Android too.
            Clipboard.copy(text)
            self._message("Share report", f"Share sheet was unavailable. Report copied to clipboard.\n\n{exc}")

    def _share_crash_report(self):
        app = MDApp.get_running_app()
        path = app.crash_report_path
        if not os.path.isfile(path):
            self._message("Crash report", "No crash report is currently saved.")
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            self._message("Crash report", str(exc))
            return
        self._share_text(text)

    def _clear_crash(self, dialog, path):
        try:
            os.remove(path)
        except OSError:
            pass
        dialog.dismiss()

    @staticmethod
    def _message(title, text):
        dialog = MDDialog(title=title, text=text,
                          buttons=[MDFlatButton(text="OK", on_release=lambda *_: dialog.dismiss())])
        dialog.open()

    def go_home(self):
        MDApp.get_running_app().go_to("home")
