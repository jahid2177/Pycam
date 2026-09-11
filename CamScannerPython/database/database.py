"""
SQLite-backed document store.

Schema (see spec section 15, extended in step 9 with `pages_json`):
    documents(id, name, created_at, updated_at, page_count,
              file_path, thumbnail_path, ocr_text, document_type,
              pages_json)

`pages_json` holds the ordered list of this document's page image
paths, as a JSON array - it's the source of truth for a multi-page
document until step 11 (PDF export) gives documents a single exported
file; `file_path` continues to point at a single representative image
(currently the first page) so existing single-image assumptions
elsewhere don't break.

This module is the only place that touches the `documents` table -
every screen goes through DocumentDatabase rather than writing raw SQL,
so the schema can change in one place later.
"""

import json
import sqlite3
import threading
from datetime import datetime
from typing import List, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    page_count      INTEGER NOT NULL DEFAULT 0,
    file_path       TEXT NOT NULL,
    thumbnail_path  TEXT,
    ocr_text        TEXT,
    document_type   TEXT NOT NULL DEFAULT 'document',
    pages_json      TEXT
);
"""

INDEX = """
CREATE INDEX IF NOT EXISTS idx_documents_updated_at
ON documents (updated_at DESC);
"""


class DocumentDatabase:
    """Thread-safe wrapper around the sqlite3 connection.

    Kivy's UI runs on the main thread, but scanning/OCR work happens on
    worker threads, so every public method acquires `_lock` before
    touching the connection.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    def initialize(self):
        if self._conn is not None:
            return
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute(SCHEMA)
            self._conn.execute(INDEX)
            self._conn.commit()
            self._migrate_pages_json()

    def _migrate_pages_json(self):
        """Add pages_json to a database created before step 9, without
        needing a full migration framework at this stage of the app."""
        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(documents)").fetchall()
        }
        if "pages_json" not in columns:
            self._conn.execute("ALTER TABLE documents ADD COLUMN pages_json TEXT")
            self._conn.commit()

    def _ensure_ready(self):
        if self._conn is None:
            self.initialize()

    # ---- Create -----------------------------------------------------

    def create_document(
        self,
        name: str,
        file_path: str,
        page_count: int = 1,
        thumbnail_path: Optional[str] = None,
        ocr_text: Optional[str] = None,
        document_type: str = "document",
        pages: Optional[List[str]] = None,
    ) -> int:
        self._ensure_ready()
        now = datetime.utcnow().isoformat()
        pages_json = json.dumps(pages) if pages is not None else None
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO documents
                    (name, created_at, updated_at, page_count,
                     file_path, thumbnail_path, ocr_text, document_type,
                     pages_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, now, now, page_count, file_path,
                 thumbnail_path, ocr_text, document_type, pages_json),
            )
            self._conn.commit()
            return cursor.lastrowid

    # ---- Read ---------------------------------------------------------

    def list_documents(self, search: Optional[str] = None) -> list:
        self._ensure_ready()
        with self._lock:
            if search:
                rows = self._conn.execute(
                    """
                    SELECT * FROM documents
                    WHERE name LIKE ? OR ocr_text LIKE ?
                    ORDER BY updated_at DESC
                    """,
                    (f"%{search}%", f"%{search}%"),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM documents ORDER BY updated_at DESC"
                ).fetchall()
            return [dict(row) for row in rows]

    def get_document(self, document_id: int) -> Optional[dict]:
        self._ensure_ready()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_pages(self, document_id: int) -> List[str]:
        """Ordered list of page image paths for a document, or a
        single-item list from file_path for a document saved before
        pages_json existed."""
        document = self.get_document(document_id)
        if not document:
            return []
        raw = document.get("pages_json")
        if raw:
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                pass
        return [document["file_path"]] if document.get("file_path") else []

    def count_documents(self) -> int:
        self._ensure_ready()
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM documents"
            ).fetchone()
            return row["c"] if row else 0

    # ---- Update ---------------------------------------------------------

    def rename_document(self, document_id: int, new_name: str):
        self._ensure_ready()
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET name = ?, updated_at = ? WHERE id = ?",
                (new_name, now, document_id),
            )
            self._conn.commit()

    def update_pages(self, document_id: int, pages: List[str]):
        """Replace a document's page list (e.g. after re-editing in
        step 10) and keep file_path/page_count/thumbnail_path in sync
        with it."""
        self._ensure_ready()
        now = datetime.utcnow().isoformat()
        pages_json = json.dumps(pages)
        first_page = pages[0] if pages else None
        with self._lock:
            self._conn.execute(
                """
                UPDATE documents
                SET pages_json = ?, page_count = ?, file_path = COALESCE(?, file_path),
                    thumbnail_path = COALESCE(?, thumbnail_path), updated_at = ?
                WHERE id = ?
                """,
                (pages_json, len(pages), first_page, first_page, now, document_id),
            )
            self._conn.commit()

    def update_ocr_text(self, document_id: int, ocr_text: str):
        self._ensure_ready()
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET ocr_text = ?, updated_at = ? WHERE id = ?",
                (ocr_text, now, document_id),
            )
            self._conn.commit()

    def touch(self, document_id: int):
        """Bump updated_at, e.g. after re-exporting or editing pages."""
        self._ensure_ready()
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET updated_at = ? WHERE id = ?",
                (now, document_id),
            )
            self._conn.commit()

    # ---- Delete ---------------------------------------------------------

    def delete_document(self, document_id: int):
        self._ensure_ready()
        with self._lock:
            self._conn.execute(
                "DELETE FROM documents WHERE id = ?", (document_id,)
            )
            self._conn.commit()

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None
