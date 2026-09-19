"""Encrypted private-document vault.

Protected document pages are encrypted with AES-CTR and authenticated with
HMAC-SHA256 (encrypt-then-MAC). The randomly generated master key is stored in
app-private preferences; encrypted page files live in the app-private vault.
This primarily protects document content at rest from casual file-system access
and shared-storage exposure. App PIN/biometric remains the interactive access
gate.
"""

import hashlib
import hmac
import os
import shutil
from pathlib import Path

MAGIC = b"PCV1"
NONCE_SIZE = 16
TAG_SIZE = 32
CHUNK = 1024 * 1024


def _require_aes():
    try:
        import pyaes
        return pyaes
    except Exception as exc:
        raise RuntimeError("Encrypted private folder requires the bundled pyaes module.") from exc


def _master_key(prefs) -> bytes:
    raw = prefs.get("vault_master_key") or ""
    if raw:
        try:
            key = bytes.fromhex(raw)
            if len(key) == 32:
                return key
        except Exception:
            pass
    key = os.urandom(32)
    prefs.set("vault_master_key", key.hex())
    return key


def _keys(prefs):
    master = _master_key(prefs)
    blob = hashlib.sha512(master + b"PycamPrivateVaultV1").digest()
    return blob[:32], blob[32:64]


def is_encrypted_path(path: str) -> bool:
    return bool(path) and str(path).lower().endswith(".pcv")


def encrypt_file(src: str, dst: str, prefs, *, remove_source=False) -> str:
    pyaes = _require_aes()
    enc_key, mac_key = _keys(prefs)
    nonce = os.urandom(NONCE_SIZE)
    counter = pyaes.Counter(int.from_bytes(nonce, "big"))
    aes = pyaes.AESModeOfOperationCTR(enc_key, counter=counter)
    mac = hmac.new(mac_key, MAGIC + nonce, hashlib.sha256)

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".tmp"
    try:
        with open(src, "rb") as fin, open(tmp, "wb") as fout:
            fout.write(MAGIC)
            fout.write(nonce)
            while True:
                chunk = fin.read(CHUNK)
                if not chunk:
                    break
                cipher = aes.encrypt(chunk)
                mac.update(cipher)
                fout.write(cipher)
            fout.write(mac.digest())
        os.replace(tmp, dst)
        if remove_source:
            try:
                os.remove(src)
            except OSError:
                pass
        return dst
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def decrypt_file(src: str, dst: str, prefs) -> str:
    pyaes = _require_aes()
    enc_key, mac_key = _keys(prefs)
    total = os.path.getsize(src)
    if total < len(MAGIC) + NONCE_SIZE + TAG_SIZE:
        raise ValueError("Encrypted vault file is truncated.")

    with open(src, "rb") as fin:
        magic = fin.read(len(MAGIC))
        if magic != MAGIC:
            raise ValueError("Invalid private vault file.")
        nonce = fin.read(NONCE_SIZE)
        ciphertext_len = total - len(MAGIC) - NONCE_SIZE - TAG_SIZE
        mac = hmac.new(mac_key, MAGIC + nonce, hashlib.sha256)
        counter = pyaes.Counter(int.from_bytes(nonce, "big"))
        aes = pyaes.AESModeOfOperationCTR(enc_key, counter=counter)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + ".tmp"
        try:
            remaining = ciphertext_len
            with open(tmp, "wb") as fout:
                while remaining:
                    chunk = fin.read(min(CHUNK, remaining))
                    if not chunk:
                        raise ValueError("Encrypted vault file is truncated.")
                    remaining -= len(chunk)
                    mac.update(chunk)
                    fout.write(aes.decrypt(chunk))
                stored_tag = fin.read(TAG_SIZE)
            if not hmac.compare_digest(mac.digest(), stored_tag):
                raise ValueError("Private vault integrity check failed.")
            os.replace(tmp, dst)
            return dst
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def _vault_root(app) -> str:
    root = os.path.join(app.storage.root, "private_vault")
    os.makedirs(root, exist_ok=True)
    return root


def _unlock_root(app, document_id: int) -> str:
    root = os.path.join(os.path.join(app.storage.root, app.storage.TEMP_DIR), "private_unlock", str(document_id))
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root, exist_ok=True)
    return root


def _plain_ext(path: str, fallback=".jpg"):
    suffix = Path(path).suffix.lower()
    if suffix == ".pcv":
        name = Path(path).stem
        suffix2 = Path(name).suffix.lower()
        return suffix2 or fallback
    return suffix or fallback


def store_document_pages(app, document_id: int, pages) -> list:
    """Encrypt all supplied page files, update DB, and remove plaintext inputs.

    Existing encrypted files are first materialized only if needed; callers
    normally pass editor/temp plaintext pages.
    """
    root = os.path.join(_vault_root(app), f"doc_{document_id}")
    staged = root + ".staging"
    shutil.rmtree(staged, ignore_errors=True)
    os.makedirs(staged, exist_ok=True)
    encrypted = []
    try:
        for idx, src in enumerate(pages, start=1):
            if is_encrypted_path(src):
                # Keep already encrypted source by copying into the new atomic set.
                ext = _plain_ext(src)
                dst = os.path.join(staged, f"page_{idx:03d}{ext}.pcv")
                shutil.copy2(src, dst)
            else:
                ext = _plain_ext(src)
                dst = os.path.join(staged, f"page_{idx:03d}{ext}.pcv")
                encrypt_file(src, dst, app.prefs, remove_source=False)
            encrypted.append(dst)

        shutil.rmtree(root, ignore_errors=True)
        os.replace(staged, root)
        final_paths = [os.path.join(root, os.path.basename(p)) for p in encrypted]
        app.db.update_pages(document_id, final_paths, thumbnail_path="")
        app.db.set_protected(document_id, True)

        # Delete plaintext editor/materialized copies only after DB+vault success.
        for src in pages:
            if not is_encrypted_path(src):
                try:
                    os.remove(src)
                except OSError:
                    pass
        return final_paths
    except Exception:
        shutil.rmtree(staged, ignore_errors=True)
        raise


def protect_document(app, document_id: int) -> list:
    document = app.db.get_document(document_id) or {}
    pages = app.db.get_pages(document_id)
    if not pages:
        raise ValueError("Document has no pages to protect.")
    result = store_document_pages(app, document_id, pages)
    # Remove cached/plain thumbnail after encrypted pages are safely committed.
    thumb = document.get("thumbnail_path")
    if thumb and os.path.isfile(thumb):
        try:
            os.remove(thumb)
        except OSError:
            pass
    return result


def materialize_document_pages(app, document_id: int) -> tuple[list, str | None]:
    pages = app.db.get_pages(document_id)
    if not pages:
        return [], None
    if not any(is_encrypted_path(p) for p in pages):
        return list(pages), None
    root = _unlock_root(app, document_id)
    result = []
    for idx, src in enumerate(pages, start=1):
        if not is_encrypted_path(src):
            result.append(src)
            continue
        ext = _plain_ext(src)
        dst = os.path.join(root, f"page_{idx:03d}{ext}")
        decrypt_file(src, dst, app.prefs)
        result.append(dst)
    return result, root


def unprotect_document(app, document_id: int) -> list:
    pages, temp_root = materialize_document_pages(app, document_id)
    if not pages:
        raise ValueError("Document has no pages.")
    target = app.storage.get_document_dir(document_id)
    os.makedirs(target, exist_ok=True)
    out = []
    for idx, src in enumerate(pages, start=1):
        ext = _plain_ext(src)
        dst = os.path.join(target, f"page_{idx:03d}{ext}")
        shutil.copy2(src, dst)
        out.append(dst)
    app.db.update_pages(document_id, out, thumbnail_path=(out[0] if out else ""))
    app.db.set_protected(document_id, False)
    shutil.rmtree(os.path.join(_vault_root(app), f"doc_{document_id}"), ignore_errors=True)
    if temp_root:
        shutil.rmtree(temp_root, ignore_errors=True)
    return out


def cleanup_materialized(path: str | None):
    if path:
        shutil.rmtree(path, ignore_errors=True)


def verify_encrypted_file(src: str, prefs) -> dict:
    """Verify an encrypted vault file without writing plaintext to disk."""
    _require_aes()  # Fail early when the runtime dependency is missing.
    _enc_key, mac_key = _keys(prefs)
    result = {"path": src, "ok": False, "size": 0, "error": ""}
    try:
        total = os.path.getsize(src)
        result["size"] = total
        if total < len(MAGIC) + NONCE_SIZE + TAG_SIZE:
            raise ValueError("Encrypted vault file is truncated.")
        with open(src, "rb") as fin:
            magic = fin.read(len(MAGIC))
            if magic != MAGIC:
                raise ValueError("Invalid private vault file header.")
            nonce = fin.read(NONCE_SIZE)
            ciphertext_len = total - len(MAGIC) - NONCE_SIZE - TAG_SIZE
            mac = hmac.new(mac_key, MAGIC + nonce, hashlib.sha256)
            remaining = ciphertext_len
            while remaining:
                chunk = fin.read(min(CHUNK, remaining))
                if not chunk:
                    raise ValueError("Encrypted vault file is truncated.")
                remaining -= len(chunk)
                mac.update(chunk)
            stored_tag = fin.read(TAG_SIZE)
            if not hmac.compare_digest(mac.digest(), stored_tag):
                raise ValueError("Private vault integrity check failed.")
        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
    return result


def vault_key_fingerprint(prefs) -> str:
    """Non-secret fingerprint used to match a backup with its encrypted vault."""
    raw = prefs.get("vault_master_key") or ""
    if not raw:
        return ""
    try:
        key = bytes.fromhex(raw)
        if len(key) != 32:
            return ""
    except Exception:
        return ""
    return hashlib.sha256(key).hexdigest()[:16]


def scan_vault_integrity(app) -> dict:
    """Scan DB references and all encrypted vault files.

    Returns a JSON-serialisable report; it never decrypts page content to disk.
    """
    docs = app.db.list_documents(include_deleted=True)
    referenced = set()
    issues = []
    checked = 0
    healthy = 0

    for doc in docs:
        if not doc.get("protected"):
            continue
        doc_id = int(doc.get("id"))
        pages = app.db.get_pages(doc_id)
        if not pages:
            issues.append({"document_id": doc_id, "type": "missing_pages", "message": "Protected document has no page references."})
            continue
        for page in pages:
            checked += 1
            path = os.path.abspath(page)
            referenced.add(path)
            if not is_encrypted_path(path):
                issues.append({"document_id": doc_id, "path": path, "type": "plaintext_reference", "message": "Protected document references a non-encrypted page."})
                continue
            if not os.path.isfile(path):
                issues.append({"document_id": doc_id, "path": path, "type": "missing_file", "message": "Encrypted page file is missing."})
                continue
            status = verify_encrypted_file(path, app.prefs)
            if status["ok"]:
                healthy += 1
            else:
                issues.append({"document_id": doc_id, "path": path, "type": "integrity_failure", "message": status["error"]})

    orphaned = []
    root = _vault_root(app)
    for current, _dirs, files in os.walk(root):
        for name in files:
            if not name.lower().endswith(".pcv"):
                continue
            path = os.path.abspath(os.path.join(current, name))
            if path not in referenced:
                orphaned.append(path)

    return {
        "ok": not issues,
        "protected_documents": sum(1 for d in docs if d.get("protected")),
        "checked_pages": checked,
        "healthy_pages": healthy,
        "issues": issues,
        "orphaned_files": orphaned,
        "key_fingerprint": vault_key_fingerprint(app.prefs),
    }


def repair_missing_vault_paths(app) -> dict:
    """Conservatively repair DB page paths from a document's own vault folder.

    Only missing encrypted references are repaired, and only when the number of
    discovered page files exactly matches the document's expected page count.
    Corrupt files are never replaced or deleted automatically.
    """
    repaired = []
    skipped = []
    docs = app.db.list_documents(include_deleted=True)
    for doc in docs:
        if not doc.get("protected"):
            continue
        doc_id = int(doc["id"])
        pages = app.db.get_pages(doc_id)
        if pages and all(os.path.isfile(p) for p in pages):
            continue
        folder = os.path.join(_vault_root(app), f"doc_{doc_id}")
        candidates = []
        if os.path.isdir(folder):
            candidates = sorted(
                os.path.join(folder, n) for n in os.listdir(folder)
                if n.lower().endswith(".pcv") and os.path.isfile(os.path.join(folder, n))
            )
        expected = int(doc.get("page_count") or len(pages) or 0)
        if candidates and (expected <= 0 or len(candidates) == expected):
            if all(verify_encrypted_file(p, app.prefs)["ok"] for p in candidates):
                app.db.update_pages(doc_id, candidates, thumbnail_path="")
                repaired.append(doc_id)
                continue
        skipped.append(doc_id)
    return {"repaired": repaired, "skipped": skipped}
