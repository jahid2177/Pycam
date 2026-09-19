"""Local, portable backup/restore for Pycam app-private data.

Backups include the SQLite database, preferences (including the private-vault
master key), document pages/thumbnails, encrypted vault files, a versioned
manifest and SHA-256 checksums. Restore validates the archive before replacing
current data.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime

BACKUP_VERSION = 2
_ALLOWED_TOP_LEVEL = {"documents", "thumbnails", "private_vault"}
_ALLOWED_FILES = {"documents.db", "preferences.json"}
_MANIFEST = "backup_manifest.json"


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_zip_member(zf, name: str) -> str:
    h = hashlib.sha256()
    with zf.open(name, "r") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _prefs_vault_fingerprint(prefs_path: str) -> str:
    try:
        data = json.load(open(prefs_path, "r", encoding="utf-8"))
        raw = data.get("vault_master_key") or ""
        key = bytes.fromhex(raw)
        if len(key) != 32:
            return ""
        return hashlib.sha256(key).hexdigest()[:16]
    except Exception:
        return ""


def create_backup(storage_manager) -> str:
    root = os.path.abspath(storage_manager.root)
    exports = os.path.join(root, storage_manager.EXPORTS_DIR)
    os.makedirs(exports, exist_ok=True)
    out = os.path.join(exports, f"Pycam_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")

    snapshot = os.path.join(root, "backup_documents.db.tmp")
    src_db = storage_manager.get_database_path()
    if os.path.exists(src_db):
        src = sqlite3.connect(src_db); dst = sqlite3.connect(snapshot)
        try:
            src.backup(dst)
        finally:
            dst.close(); src.close()

    entries = []
    prefs = os.path.join(root, "preferences.json")
    try:
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            def add_file(full, arc):
                zf.write(full, arc)
                entries.append({"path": arc, "size": os.path.getsize(full), "sha256": _sha256_file(full)})

            if os.path.exists(snapshot):
                add_file(snapshot, "documents.db")
            if os.path.isfile(prefs):
                add_file(prefs, "preferences.json")
            for folder in sorted(_ALLOWED_TOP_LEVEL):
                base = os.path.join(root, folder)
                if not os.path.isdir(base):
                    continue
                for current, _dirs, files in os.walk(base):
                    for name in sorted(files):
                        full = os.path.join(current, name)
                        rel = os.path.relpath(full, root).replace(os.sep, "/")
                        add_file(full, rel)

            encrypted_count = sum(1 for e in entries if e["path"].startswith("private_vault/") and e["path"].endswith(".pcv"))
            fingerprint = _prefs_vault_fingerprint(prefs) if os.path.isfile(prefs) else ""
            if encrypted_count and not fingerprint:
                raise ValueError("Encrypted vault exists but its master key is missing from preferences; portable backup aborted.")
            manifest = {
                "backup_version": BACKUP_VERSION,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "encrypted_vault_files": encrypted_count,
                "vault_key_fingerprint": fingerprint,
                "entries": entries,
            }
            zf.writestr(_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
    finally:
        try: os.remove(snapshot)
        except OSError: pass

    validate_backup(out, verify_checksums=True)
    return out


def _safe_member(name: str) -> bool:
    normalized = name.replace("\\", "/").lstrip("/")
    if not normalized or normalized.startswith("../") or "/../" in normalized:
        return False
    if normalized in _ALLOWED_FILES or normalized in {_MANIFEST, "backup_version.txt"}:
        return True
    return normalized.split("/", 1)[0] in _ALLOWED_TOP_LEVEL


def validate_backup(zip_path: str, *, verify_checksums=True) -> dict:
    if not zipfile.is_zipfile(zip_path):
        raise ValueError("Selected file is not a valid ZIP backup.")
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        if "documents.db" not in names:
            raise ValueError("Backup does not contain documents.db.")
        for name in names:
            if not _safe_member(name):
                raise ValueError(f"Unsafe or unsupported backup entry: {name}")

        # Backward compatibility: v1 backups have no manifest.
        if _MANIFEST not in names:
            return {"backup_version": 1, "legacy": True, "verified_entries": 0, "encrypted_vault_files": 0}

        try:
            manifest = json.loads(zf.read(_MANIFEST).decode("utf-8"))
        except Exception as exc:
            raise ValueError("Backup manifest is invalid.") from exc
        if int(manifest.get("backup_version", 0)) > BACKUP_VERSION:
            raise ValueError("Backup was created by a newer unsupported Pycam version.")

        entries = manifest.get("entries") or []
        by_name = {e.get("path"): e for e in entries if isinstance(e, dict)}
        encrypted = int(manifest.get("encrypted_vault_files") or 0)
        if encrypted:
            if "preferences.json" not in names:
                raise ValueError("Encrypted backup is missing preferences.json and cannot restore its vault key.")
            with tempfile.TemporaryDirectory(prefix="pycam_backup_key_") as td:
                pp = os.path.join(td, "preferences.json")
                with open(pp, "wb") as f: f.write(zf.read("preferences.json"))
                fp = _prefs_vault_fingerprint(pp)
            if not fp or fp != (manifest.get("vault_key_fingerprint") or ""):
                raise ValueError("Encrypted backup vault-key fingerprint does not match preferences.json.")

        verified = 0
        if verify_checksums:
            for name, meta in by_name.items():
                if name not in names:
                    raise ValueError(f"Backup entry is missing: {name}")
                actual = _sha256_zip_member(zf, name)
                if actual != meta.get("sha256"):
                    raise ValueError(f"Backup checksum mismatch: {name}")
                verified += 1
        return {**manifest, "legacy": False, "verified_entries": verified}


def restore_backup(zip_path: str, storage_manager, database=None) -> dict:
    info = validate_backup(zip_path, verify_checksums=True)
    root = os.path.abspath(storage_manager.root)
    parent = os.path.dirname(root)
    staging = tempfile.mkdtemp(prefix="pycam_restore_", dir=parent)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                if member.filename in {_MANIFEST, "backup_version.txt"}:
                    continue
                if not _safe_member(member.filename):
                    continue
                target = os.path.abspath(os.path.join(staging, member.filename))
                if not (target == staging or target.startswith(staging + os.sep)):
                    raise ValueError("Backup contains an invalid path.")
                if member.is_dir():
                    os.makedirs(target, exist_ok=True); continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(member, "r") as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        if database is not None: database.close()
        for folder in _ALLOWED_TOP_LEVEL:
            existing = os.path.join(root, folder); incoming = os.path.join(staging, folder)
            if os.path.isdir(existing): shutil.rmtree(existing, ignore_errors=True)
            if os.path.isdir(incoming): shutil.copytree(incoming, existing)
            else: os.makedirs(existing, exist_ok=True)
        for name in _ALLOWED_FILES:
            incoming = os.path.join(staging, name)
            if os.path.isfile(incoming): shutil.copy2(incoming, os.path.join(root, name))
        storage_manager._ensure_dirs()
        if database is not None: database.initialize()
        return info
    finally:
        shutil.rmtree(staging, ignore_errors=True)
