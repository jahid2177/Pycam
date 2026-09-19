"""
SQLite-backed document store.

Schema (see spec section 15, extended in step 9 with `pages_json`):
    documents(id, name, created_at, updated_at, page_count,
              file_path, thumbnail_path, ocr_text, document_type,
              pages_json, folder, tags_json, favorite, deleted_at)

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
from datetime import datetime, timedelta, timezone
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
    pages_json      TEXT,
    folder          TEXT NOT NULL DEFAULT '',
    tags_json       TEXT,
    favorite        INTEGER NOT NULL DEFAULT 0,
    deleted_at      TEXT,
    protected       INTEGER NOT NULL DEFAULT 0
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
            self._migrate_schema()

    def _migrate_schema(self):
        """Add newer document-management columns without losing old data."""
        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(documents)").fetchall()
        }
        additions = {
            "pages_json": "TEXT",
            "folder": "TEXT NOT NULL DEFAULT ''",
            "tags_json": "TEXT",
            "favorite": "INTEGER NOT NULL DEFAULT 0",
            "deleted_at": "TEXT",
            "protected": "INTEGER NOT NULL DEFAULT 0",
        }
        changed = False
        for name, sql_type in additions.items():
            if name not in columns:
                self._conn.execute(
                    f"ALTER TABLE documents ADD COLUMN {name} {sql_type}"
                )
                changed = True
        if changed:
            self._conn.commit()

    def _ensure_ready(self):
        if self._conn is None:
            self.initialize()

    def integrity_check(self) -> dict:
        """Run lightweight SQLite integrity/schema checks without mutating data."""
        self._ensure_ready()
        with self._lock:
            quick = self._conn.execute("PRAGMA quick_check").fetchone()[0]
            columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(documents)").fetchall()}
        required = {
            "id", "name", "created_at", "updated_at", "page_count",
            "file_path", "thumbnail_path", "ocr_text", "document_type",
            "pages_json", "folder", "tags_json", "favorite", "deleted_at", "protected",
        }
        missing = sorted(required - columns)
        return {
            "ok": str(quick).lower() == "ok" and not missing,
            "quick_check": str(quick),
            "missing_columns": missing,
        }

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
        now = datetime.now(timezone.utc).isoformat()
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

    def list_documents(
        self,
        search: Optional[str] = None,
        *,
        include_deleted: bool = False,
        favorites_only: bool = False,
        folder: Optional[str] = None,
        tag: Optional[str] = None,
        document_type: Optional[str] = None,
        sort_by: str = "modified_desc",
    ) -> list:
        self._ensure_ready()
        clauses = [] if include_deleted else ["deleted_at IS NULL"]
        params = []
        if search:
            clauses.append("(name LIKE ? OR ocr_text LIKE ? OR tags_json LIKE ?)")
            token = f"%{search}%"
            params.extend([token, token, token])
        if favorites_only:
            clauses.append("favorite = 1")
        if folder is not None:
            clauses.append("folder = ?")
            params.append(folder)
        if tag:
            clauses.append("tags_json LIKE ?")
            params.append(f'%"{tag}"%')
        if document_type:
            clauses.append("document_type = ?")
            params.append(document_type)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        order_map = {
            "modified_desc": "favorite DESC, updated_at DESC",
            "modified_asc": "favorite DESC, updated_at ASC",
            "name_asc": "favorite DESC, name COLLATE NOCASE ASC",
            "name_desc": "favorite DESC, name COLLATE NOCASE DESC",
            "pages_desc": "favorite DESC, page_count DESC, updated_at DESC",
            "created_desc": "favorite DESC, created_at DESC",
        }
        order_sql = order_map.get(sort_by, order_map["modified_desc"])
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM documents" + where + " ORDER BY " + order_sql,
                params,
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                try:
                    item["tags"] = json.loads(item.get("tags_json") or "[]")
                except Exception:
                    item["tags"] = []
                item["favorite"] = bool(item.get("favorite"))
                item["protected"] = bool(item.get("protected"))
                result.append(item)
            return result

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

    def count_documents(self, include_deleted: bool = False) -> int:
        self._ensure_ready()
        query = "SELECT COUNT(*) AS c FROM documents"
        if not include_deleted:
            query += " WHERE deleted_at IS NULL"
        with self._lock:
            row = self._conn.execute(query).fetchone()
            return row["c"] if row else 0

    def list_folders(self) -> List[str]:
        self._ensure_ready()
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT folder FROM documents WHERE deleted_at IS NULL AND folder <> '' ORDER BY folder COLLATE NOCASE"
            ).fetchall()
        return [row["folder"] for row in rows if row["folder"]]


    def list_document_types(self) -> List[str]:
        self._ensure_ready()
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT document_type FROM documents WHERE deleted_at IS NULL AND document_type <> '' ORDER BY document_type COLLATE NOCASE"
            ).fetchall()
        return [row["document_type"] for row in rows if row["document_type"]]

    def list_tags(self) -> List[str]:
        tags = set()
        for doc in self.list_documents():
            tags.update(doc.get("tags") or [])
        return sorted(tags, key=str.lower)

    # ---- Update ---------------------------------------------------------

    def rename_document(self, document_id: int, new_name: str):
        self._ensure_ready()
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET name = ?, updated_at = ? WHERE id = ?",
                (new_name, now, document_id),
            )
            self._conn.commit()

    def update_pages(self, document_id: int, pages: List[str], thumbnail_path=None):
        """Replace a document's ordered page list and keep representative paths in sync.

        ``thumbnail_path`` defaults to the first page for normal documents. Pass an
        empty string for encrypted/private documents so plaintext thumbnails are not
        retained.
        """
        self._ensure_ready()
        now = datetime.now(timezone.utc).isoformat()
        pages_json = json.dumps(pages)
        first_page = pages[0] if pages else None
        thumb = first_page if thumbnail_path is None else thumbnail_path
        with self._lock:
            self._conn.execute(
                """
                UPDATE documents
                SET pages_json = ?, page_count = ?, file_path = COALESCE(?, file_path),
                    thumbnail_path = ?, updated_at = ?
                WHERE id = ?
                """,
                (pages_json, len(pages), first_page, thumb, now, document_id),
            )
            self._conn.commit()

    def update_ocr_text(self, document_id: int, ocr_text: str):
        self._ensure_ready()
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET ocr_text = ?, updated_at = ? WHERE id = ?",
                (ocr_text, now, document_id),
            )
            self._conn.commit()

    def touch(self, document_id: int):
        """Bump updated_at, e.g. after re-exporting or editing pages."""
        self._ensure_ready()
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET updated_at = ? WHERE id = ?",
                (now, document_id),
            )
            self._conn.commit()


    def set_favorite(self, document_id: int, favorite: bool):
        self._ensure_ready()
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET favorite = ?, updated_at = ? WHERE id = ?",
                (1 if favorite else 0, now, document_id),
            )
            self._conn.commit()

    def set_protected(self, document_id: int, protected: bool):
        self._ensure_ready()
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET protected = ?, updated_at = ? WHERE id = ?",
                (1 if protected else 0, now, document_id),
            )
            self._conn.commit()

    def clear_all_protected(self):
        self._ensure_ready()
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET protected = 0, updated_at = ? WHERE protected = 1",
                (now,),
            )
            self._conn.commit()

    def set_folder(self, document_id: int, folder: str):
        self._ensure_ready()
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET folder = ?, updated_at = ? WHERE id = ?",
                ((folder or "").strip(), now, document_id),
            )
            self._conn.commit()

    def set_tags(self, document_id: int, tags: List[str]):
        self._ensure_ready()
        clean = []
        seen = set()
        for tag in tags:
            value = str(tag).strip()
            key = value.lower()
            if value and key not in seen:
                seen.add(key)
                clean.append(value)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET tags_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(clean, ensure_ascii=False), now, document_id),
            )
            self._conn.commit()

    def move_to_trash(self, document_id: int):
        self._ensure_ready()
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET deleted_at = ?, updated_at = ? WHERE id = ?",
                (now, now, document_id),
            )
            self._conn.commit()

    def restore_document(self, document_id: int):
        self._ensure_ready()
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET deleted_at = NULL, updated_at = ? WHERE id = ?",
                (now, document_id),
            )
            self._conn.commit()

    # ---- Delete ---------------------------------------------------------

    def delete_document(self, document_id: int):
        """Backward-compatible delete: move to Trash instead of destroying data."""
        self.move_to_trash(document_id)

    def permanent_delete_document(self, document_id: int):
        self._ensure_ready()
        with self._lock:
            self._conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            self._conn.commit()


    def purge_trash_older_than(self, days: int) -> int:
        """Permanently delete documents that have remained in Trash past `days`."""
        self._ensure_ready()
        days = int(days)
        if days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM documents WHERE deleted_at IS NOT NULL AND deleted_at < ?",
                (cutoff,),
            )
            self._conn.commit()
            return max(0, int(cur.rowcount or 0))

    def close(self):
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
