"""AI document-assistant screen using a user-configured compatible API."""
from __future__ import annotations

import threading

from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField
from kivymd.uix.toolbar import MDTopAppBar

from storage.ai_client import build_messages, chat_completion


class AIChatScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.history = []
        self.document_context = ""
        self._busy = False

        root = MDBoxLayout(orientation="vertical")
        bar = MDTopAppBar(title="AI Document Assistant", elevation=0)
        bar.left_action_items = [["arrow-left", lambda *_: MDApp.get_running_app().go_to("tools")]]
        root.add_widget(bar)

        scroll = ScrollView(do_scroll_x=False)
        body = MDBoxLayout(orientation="vertical", adaptive_height=True,
                           padding=(dp(14), dp(10)), spacing=dp(8))
        self.endpoint = MDTextField(hint_text="API base URL (example: https://provider.example/v1)", mode="rectangle")
        self.model = MDTextField(hint_text="Model name", mode="rectangle")
        self.key = MDTextField(hint_text="API key (session only; not saved)", password=True, mode="rectangle")
        body.add_widget(self.endpoint); body.add_widget(self.model); body.add_widget(self.key)

        config_row = MDBoxLayout(orientation="horizontal", adaptive_height=True, spacing=dp(6))
        config_row.add_widget(MDFlatButton(text="SAVE ENDPOINT/MODEL", on_release=lambda *_: self._save_config()))
        config_row.add_widget(MDFlatButton(text="CLEAR CHAT", on_release=lambda *_: self._clear()))
        body.add_widget(config_row)

        context_row = MDBoxLayout(orientation="horizontal", adaptive_height=True, spacing=dp(6))
        context_row.add_widget(MDRaisedButton(text="USE CURRENT SCAN", on_release=lambda *_: self._load_current_scan()))
        context_row.add_widget(MDFlatButton(text="USE SELECTED DOCUMENT", on_release=lambda *_: self._load_selected_document()))
        body.add_widget(context_row)
        self.context_status = MDLabel(text="Context: none", theme_text_color="Secondary",
                                      size_hint_y=None, height=dp(34))
        body.add_widget(self.context_status)

        self.chat = MDLabel(text="", markup=True, adaptive_height=True,
                            theme_text_color="Primary")
        body.add_widget(self.chat)
        self.question = MDTextField(hint_text="Ask about the document…", multiline=True,
                                    mode="rectangle", size_hint_y=None, height=dp(110))
        body.add_widget(self.question)
        action = MDBoxLayout(orientation="horizontal", adaptive_height=True, spacing=dp(8))
        self.send = MDRaisedButton(text="SEND", on_release=lambda *_: self._send())
        action.add_widget(self.send)
        action.add_widget(MDFlatButton(text="COPY LAST ANSWER", on_release=lambda *_: self._copy_last()))
        body.add_widget(action)
        self.status = MDLabel(text="", theme_text_color="Secondary", size_hint_y=None, height=dp(34))
        body.add_widget(self.status)
        scroll.add_widget(body)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_pre_enter(self, *args):
        app = MDApp.get_running_app()
        self.endpoint.text = app.prefs.get("ai_base_url") or ""
        self.model.text = app.prefs.get("ai_model") or ""
        # API key deliberately exists only in process memory.
        self.key.text = getattr(app, "ai_api_key", "") or ""

    def _save_config(self):
        app = MDApp.get_running_app()
        app.prefs.set("ai_base_url", self.endpoint.text.strip())
        app.prefs.set("ai_model", self.model.text.strip())
        app.ai_api_key = self.key.text.strip()
        self.status.text = "Endpoint/model saved. API key kept only for this session."

    def _ocr_pages(self, pages, label):
        if not pages:
            self._message("No pages", "There are no pages available for AI context.")
            return
        self._busy = True; self.send.disabled = True; self.status.text = "Reading document text…"
        def worker():
            try:
                from ocr.ocr_manager import run_ocr_with_fallback
                app = MDApp.get_running_app()
                language = app.prefs.get("ocr_language") or "english"
                text = run_ocr_with_fallback(pages, language)
                Clock.schedule_once(lambda *_: self._set_context(text, label), 0)
            except Exception as exc:
                Clock.schedule_once(lambda *_: self._finish_error(str(exc)), 0)
        threading.Thread(target=worker, daemon=True).start()

    def _load_current_scan(self):
        app = MDApp.get_running_app()
        self._ocr_pages(list(getattr(app, "active_session_pages", []) or []), "current scan")

    def _load_selected_document(self):
        app = MDApp.get_running_app()
        doc_id = getattr(app, "selected_document_id", None) or getattr(app, "editing_document_id", None)
        if not doc_id:
            self._message("No document selected", "Open/select a saved document first, then return to AI Chat.")
            return
        doc = app.db.get_document(int(doc_id)) or {}
        cached = (doc.get("ocr_text") or "").strip()
        if cached:
            self._set_context(cached, doc.get("name") or "selected document")
            return
        self._ocr_pages(app.db.get_pages(int(doc_id)), doc.get("name") or "selected document")

    def _set_context(self, text, label):
        self._busy = False; self.send.disabled = False
        self.document_context = (text or "").strip()
        self.context_status.text = f"Context: {label} ({len(self.document_context):,} characters)"
        self.status.text = "Document context ready." if self.document_context else "No readable text found."

    def _send(self):
        if self._busy:
            return
        question = self.question.text.strip()
        if not question:
            self.status.text = "Type a question first."
            return
        app = MDApp.get_running_app()
        self._save_config()
        base = self.endpoint.text.strip(); model = self.model.text.strip(); key = self.key.text.strip()
        try:
            messages = build_messages(self.history, question, self.document_context)
        except Exception as exc:
            self.status.text = str(exc); return
        self.history.append({"role": "user", "content": question})
        self.question.text = ""
        self._render()
        self._busy = True; self.send.disabled = True; self.status.text = "Waiting for AI response…"
        def worker():
            try:
                answer = chat_completion(base, key, model, messages)
                Clock.schedule_once(lambda *_: self._finish_answer(answer), 0)
            except Exception as exc:
                Clock.schedule_once(lambda *_: self._finish_error(str(exc)), 0)
        threading.Thread(target=worker, daemon=True).start()

    def _finish_answer(self, answer):
        self._busy = False; self.send.disabled = False
        self.history.append({"role": "assistant", "content": answer})
        self.status.text = ""
        self._render()

    def _finish_error(self, message):
        self._busy = False; self.send.disabled = False
        self.status.text = message

    def _render(self):
        chunks = []
        for item in self.history[-20:]:
            who = "You" if item["role"] == "user" else "Assistant"
            # Escape Kivy markup brackets in provider/user text.
            text = str(item["content"]).replace("[", "&bl;").replace("]", "&br;")
            chunks.append(f"[b]{who}[/b]\n{text}")
        self.chat.text = "\n\n".join(chunks)

    def _copy_last(self):
        for item in reversed(self.history):
            if item.get("role") == "assistant":
                Clipboard.copy(item.get("content", "")); self.status.text = "Last answer copied."
                return
        self.status.text = "No AI answer to copy yet."

    def _clear(self):
        self.history = []; self.document_context = ""; self.chat.text = ""
        self.context_status.text = "Context: none"; self.status.text = "Chat cleared."

    @staticmethod
    def _message(title, text):
        dialog = MDDialog(title=title, text=text, buttons=[MDFlatButton(text="OK", on_release=lambda *_: dialog.dismiss())])
        dialog.open()
