"""Android print tool screen."""

import os
import threading
import time

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.toolbar import MDTopAppBar

from storage.android_print import print_images
from storage.file_picker import FilePicker, copy_to_app_temp, render_pdf_to_images


class PrintToolScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._picker = FilePicker()
        self._print_pages = []
        self._source_label = ""
        self._running = False
        self._build_ui()

    def _build_ui(self):
        root = MDBoxLayout(orientation="vertical", md_bg_color=(0.97, 0.98, 1, 1))
        bar = MDTopAppBar(title="Print", elevation=0)
        bar.left_action_items = [["arrow-left", lambda *_: MDApp.get_running_app().go_to("tools")]]
        root.add_widget(bar)

        scroll = ScrollView(do_scroll_x=False)
        body = MDBoxLayout(
            orientation="vertical", adaptive_height=True,
            padding=(dp(18), dp(18), dp(18), dp(30)), spacing=dp(14),
        )
        body.add_widget(MDLabel(
            text=(
                "Print a PDF, image, or current scan using Android's native print dialog. "
                "You can select a printer, Save as PDF, paper size, orientation and page range there."
            ),
            theme_text_color="Secondary", size_hint_y=None, height=dp(90),
        ))

        body.add_widget(MDRaisedButton(
            text="SELECT PDF", pos_hint={"center_x": 0.5},
            on_release=lambda *_: self._picker.choose_pdf(self._on_pdf, self._picker_error),
        ))
        body.add_widget(MDRaisedButton(
            text="SELECT IMAGE", pos_hint={"center_x": 0.5},
            on_release=lambda *_: self._picker.choose_image(self._on_image, self._picker_error),
        ))
        self.current_button = MDFlatButton(
            text="USE CURRENT SCAN", pos_hint={"center_x": 0.5},
            on_release=lambda *_: self._use_current_scan(),
        )
        body.add_widget(self.current_button)

        self.selection = MDLabel(
            text="No printable document selected", halign="center",
            theme_text_color="Secondary", size_hint_y=None, height=dp(64),
        )
        body.add_widget(self.selection)

        self.print_button = MDRaisedButton(
            text="OPEN PRINT DIALOG", disabled=True,
            pos_hint={"center_x": 0.5}, on_release=lambda *_: self._print(),
        )
        body.add_widget(self.print_button)
        self.status = MDLabel(
            text="", halign="center", theme_text_color="Secondary",
            size_hint_y=None, height=dp(76),
        )
        body.add_widget(self.status)
        scroll.add_widget(body)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_pre_enter(self, *_):
        app = MDApp.get_running_app()
        self.current_button.disabled = not bool(getattr(app, "active_session_pages", []))

    def _picker_error(self, message):
        self._message("Print", str(message))

    def _on_image(self, path):
        try:
            app = MDApp.get_running_app()
            local = copy_to_app_temp(path, app.storage, prefix="print_image")
            self._set_pages([local], os.path.basename(path))
        except Exception as exc:
            self._message("Print", str(exc))

    def _on_pdf(self, path):
        if self._running:
            return
        self._running = True
        self.status.text = "Preparing PDF pages for printing..."
        self.print_button.disabled = True
        app = MDApp.get_running_app()

        def worker():
            try:
                local = copy_to_app_temp(path, app.storage, prefix="print_pdf")
                out_dir = app.storage.get_temp_path(f"print_pages_{int(time.time() * 1000)}")
                pages = render_pdf_to_images(local, out_dir)
                Clock.schedule_once(
                    lambda _dt, p=pages, n=os.path.basename(path): self._finish_pdf(p, n), 0
                )
            except Exception as exc:
                Clock.schedule_once(lambda _dt, e=str(exc): self._finish_error(e), 0)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_pdf(self, pages, name):
        self._running = False
        self._set_pages(pages, name)
        self.status.text = f"Prepared {len(pages)} page(s)."

    def _finish_error(self, message):
        self._running = False
        self.status.text = ""
        self._message("Print", message)

    def _use_current_scan(self):
        app = MDApp.get_running_app()
        pages = [p for p in getattr(app, "active_session_pages", []) if p and os.path.exists(p)]
        if not pages:
            self._message("Print", "There is no current scan to print.")
            return
        self._set_pages(pages, f"Current scan ({len(pages)} page(s))")

    def _set_pages(self, pages, label):
        self._print_pages = [p for p in pages if p and os.path.exists(p)]
        self._source_label = str(label or "Document")
        self.selection.text = (
            f"{self._source_label}\n{len(self._print_pages)} printable page(s)"
            if self._print_pages else "No printable document selected"
        )
        self.print_button.disabled = not bool(self._print_pages)

    def _print(self):
        if not self._print_pages:
            self._message("Print", "Select a PDF/image or use the current scan first.")
            return
        try:
            print_images(self._print_pages, job_name=self._source_label or "Pycam Document")
            self.status.text = "Android print dialog opened. Complete or cancel printing there."
        except Exception as exc:
            self._message("Print", str(exc))

    def _message(self, title, text):
        dialog = MDDialog(title=title, text=str(text), buttons=[])
        dialog.buttons = [MDFlatButton(text="OK", on_release=lambda *_: dialog.dismiss())]
        dialog.open()
