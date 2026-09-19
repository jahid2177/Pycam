"""Startup/runtime health checks for Pycam.

Checks are deliberately non-destructive. Startup uses the quick profile; the
Settings screen can request a deeper vault scan. Results are persisted so a
user can inspect/share them after a problem without needing logcat.
"""
from __future__ import annotations

import importlib
import ast
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

MIN_FREE_WARN = 150 * 1024 * 1024
MIN_TESS_BYTES = 100_000


def _entry(name, status, message, **extra):
    row = {"name": name, "status": status, "message": str(message)}
    row.update(extra)
    return row


def _module_check(name):
    try:
        importlib.import_module(name)
        return _entry(f"module:{name}", "ok", "Available")
    except Exception as exc:
        return _entry(f"module:{name}", "error", f"Unavailable: {exc}")


def _tessdata_checks(base_dir):
    rows = []
    root = Path(base_dir) / "assets" / "tessdata"
    for code in ("eng", "ben"):
        path = root / f"{code}.traineddata"
        if not path.is_file():
            rows.append(_entry(f"tessdata:{code}", "error", f"Missing {path.name}"))
            continue
        size = path.stat().st_size
        if size < MIN_TESS_BYTES:
            rows.append(_entry(f"tessdata:{code}", "error", f"File appears incomplete ({size} bytes)", size=size))
        else:
            rows.append(_entry(f"tessdata:{code}", "ok", f"Verified ({size} bytes)", size=size))
    return rows


def _storage_check(app):
    root = app.storage.root
    try:
        os.makedirs(root, exist_ok=True)
        probe = os.path.join(root, ".health_write_test")
        with open(probe, "wb") as fh:
            fh.write(b"ok")
        os.remove(probe)
        usage = shutil.disk_usage(root)
        status = "warn" if usage.free < MIN_FREE_WARN else "ok"
        return _entry(
            "storage",
            status,
            f"Writable; free space {usage.free / (1024*1024):.1f} MB",
            free_bytes=usage.free,
            root=root,
        )
    except Exception as exc:
        return _entry("storage", "error", f"Not writable: {exc}", root=root)


def _database_check(app):
    try:
        result = app.db.integrity_check()
        if result.get("ok"):
            return _entry("database", "ok", "SQLite quick_check passed")
        return _entry(
            "database", "error",
            f"quick_check={result.get('quick_check')}; missing columns={result.get('missing_columns') or []}",
        )
    except Exception as exc:
        return _entry("database", "error", f"Database check failed: {exc}")


def _export_destination_check(app):
    mode = app.prefs.get("export_destination") or "app"
    if mode == "custom":
        uri = app.prefs.get("export_tree_uri") or ""
        if not uri:
            return _entry("export_destination", "warn", "Custom export is selected but no folder permission is stored")
        return _entry("export_destination", "ok", "Custom SAF folder configured")
    if mode == "downloads":
        return _entry("export_destination", "ok", "Downloads export configured")
    return _entry("export_destination", "ok", "App-private export configured")


def _vault_check(app, deep=False):
    protected = [d for d in app.db.list_documents(include_deleted=True) if d.get("protected")]
    if not protected:
        return _entry("private_vault", "ok", "No protected documents")
    try:
        import pyaes  # noqa: F401
    except Exception as exc:
        return _entry("private_vault", "error", f"pyaes unavailable: {exc}")
    if not deep:
        missing = []
        for doc in protected:
            for path in app.db.get_pages(doc["id"]):
                if not os.path.isfile(path):
                    missing.append(path)
        if missing:
            return _entry("private_vault", "error", f"Missing encrypted pages: {len(missing)}")
        return _entry("private_vault", "ok", f"{len(protected)} protected document(s); file references present")
    try:
        from storage.private_vault import scan_vault_integrity
        result = scan_vault_integrity(app)
        if result.get("issues"):
            return _entry("private_vault", "error", f"Vault issues: {len(result['issues'])}")
        orphaned = len(result.get("orphaned_files") or [])
        status = "warn" if orphaned else "ok"
        return _entry(
            "private_vault", status,
            f"Verified {result.get('healthy_pages', 0)}/{result.get('checked_pages', 0)} pages; orphaned={orphaned}",
        )
    except Exception as exc:
        return _entry("private_vault", "error", f"Vault scan failed: {exc}")




def _extract_literal_assignment(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise ValueError(f"{name} assignment not found")


def _tool_route_check(base_dir):
    """Statically verify every visible Tools tile has a real app route.

    This deliberately avoids importing Kivy/KivyMD so it can run during CI and
    startup diagnostics on partially initialized installations.
    """
    try:
        base = Path(base_dir)
        tools_path = base / "ui" / "tools.py"
        main_path = base / "main.py"
        tools_source = tools_path.read_text(encoding="utf-8")
        main_source = main_path.read_text(encoding="utf-8")
        tools_tree = ast.parse(tools_source)
        main_tree = ast.parse(main_source)

        sections = _extract_literal_assignment(tools_tree, "TOOL_SECTIONS")
        lazy = _extract_literal_assignment(main_tree, "_LAZY_SCREENS")
        visible_keys = {tool[2] for _section, tools in sections for tool in tools}

        workflow = {}
        open_tool = None
        for node in ast.walk(tools_tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "open_tool":
                open_tool = node
                break
        if open_tool is None:
            raise ValueError("ToolsScreen.open_tool() not found")

        for node in ast.walk(open_tool):
            if isinstance(node, ast.Assign):
                if any(isinstance(t, ast.Name) and t.id == "workflow_screens" for t in node.targets):
                    workflow = ast.literal_eval(node.value)
                    break

        special_routes = {
            "id_cards": "scanner",
            "book_mode": "scanner",
            "opencv_crop": "crop",
            "ai_chat": "ai_chat",
            "print": "print_tool",
        }
        handled = set(workflow) | set(special_routes)
        missing_handlers = sorted(visible_keys - handled)

        missing_screens = []
        for key, screen in {**workflow, **special_routes}.items():
            if key in visible_keys and screen not in lazy:
                missing_screens.append(f"{key}->{screen}")

        # Ensure every lazy route references an existing Python source module.
        missing_modules = []
        for screen, route in lazy.items():
            module_name = route[0]
            module_path = base / (module_name.replace(".", "/") + ".py")
            if not module_path.is_file():
                missing_modules.append(f"{screen}:{module_name}")

        if missing_handlers or missing_screens or missing_modules:
            parts = []
            if missing_handlers:
                parts.append("unhandled tools=" + ", ".join(missing_handlers))
            if missing_screens:
                parts.append("missing screens=" + ", ".join(missing_screens))
            if missing_modules:
                parts.append("missing modules=" + ", ".join(missing_modules))
            return _entry("ui_routes", "error", "; ".join(parts))

        return _entry(
            "ui_routes",
            "ok",
            f"{len(visible_keys)} visible tools routed; {len(lazy)} lazy screens resolve to source modules",
            visible_tools=len(visible_keys),
            lazy_screens=len(lazy),
        )
    except Exception as exc:
        return _entry("ui_routes", "error", f"Route audit failed: {exc}")



def _localization_accessibility_check(base_dir):
    try:
        from storage.localization import missing_translation_keys
        missing = missing_translation_keys()
        problems = {lang: keys for lang, keys in missing.items() if keys}
        if problems:
            return _entry("localization_accessibility", "error", f"Missing translations: {problems}")
        base = Path(base_dir)
        required = {
            "ui/navigation.py": ("label_widget", "ensure_touch_target"),
            "ui/tools.py": ("label_widget", "ensure_touch_target"),
            "ui/settings.py": ("label_widget", "ensure_touch_target"),
        }
        missing_hooks = []
        for rel, hooks in required.items():
            text = (base / rel).read_text(encoding="utf-8")
            for hook in hooks:
                if hook not in text:
                    missing_hooks.append(f"{rel}:{hook}")
        if missing_hooks:
            return _entry("localization_accessibility", "error", "Missing accessibility hooks: " + ", ".join(missing_hooks))
        return _entry("localization_accessibility", "ok", "English/Bangla catalogue complete; semantic labels and 48dp target helpers wired")
    except Exception as exc:
        return _entry("localization_accessibility", "error", f"Localization/accessibility audit failed: {exc}")


def run_health_check(app, base_dir, *, deep=False, persist=True):
    started = time.monotonic()
    checks = []
    checks.append(_storage_check(app))
    checks.append(_database_check(app))
    checks.append(_export_destination_check(app))
    checks.append(_tool_route_check(base_dir))
    checks.append(_localization_accessibility_check(base_dir))
    try:
        from storage.android_compat import static_android_compatibility_audit, android_device_summary
        compat = static_android_compatibility_audit(base_dir)
        device = android_device_summary()
        if compat.get("ok"):
            warning_count = len(compat.get("warnings") or [])
            runtime = f"; runtime API={device.get('sdk')}" if device.get("sdk") else ""
            status = "warn" if warning_count else "ok"
            message = f"Android 12-16 compatibility audit passed ({compat.get('checks_passed', 0)} checks){runtime}"
            if warning_count:
                message += "; " + "; ".join(compat.get("warnings") or [])
            checks.append(_entry("android_compatibility", status, message))
        else:
            checks.append(_entry("android_compatibility", "error", "; ".join(compat.get("issues") or ["Unknown Android compatibility error"])))
    except Exception as exc:
        checks.append(_entry("android_compatibility", "error", f"Android compatibility audit failed: {exc}"))
    try:
        from storage.integration_check import run_static_integration_check
        integration = run_static_integration_check(base_dir)
        if integration.get("ok"):
            checks.append(_entry("integration", "ok", f"Static integration passed; lazy screens={integration.get('lazy_screen_count', 0)}"))
        else:
            checks.append(_entry("integration", "error", "; ".join(integration.get("issues") or ["Unknown integration error"])))
    except Exception as exc:
        checks.append(_entry("integration", "error", f"Integration check failed: {exc}"))
    checks.extend(_tessdata_checks(base_dir))
    for module in ("cv2", "numpy", "PIL", "pypdf", "reportlab", "qrcode"):
        checks.append(_module_check(module))
    checks.append(_vault_check(app, deep=deep))

    errors = sum(1 for x in checks if x["status"] == "error")
    warnings = sum(1 for x in checks if x["status"] == "warn")
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "profile": "deep" if deep else "quick",
        "ok": errors == 0,
        "errors": errors,
        "warnings": warnings,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "checks": checks,
    }
    if persist:
        write_health_report(app, report)
    return report


def health_report_paths(app):
    return (
        os.path.join(app.storage.root, "health_check.json"),
        os.path.join(app.storage.root, "health_check.txt"),
    )


def format_health_report(report):
    lines = [
        "PYCAM HEALTH CHECK",
        "=" * 60,
        f"Generated: {report.get('generated_at')}",
        f"Profile: {report.get('profile')}",
        f"Status: {'PASS' if report.get('ok') else 'NEEDS ATTENTION'}",
        f"Errors: {report.get('errors', 0)} | Warnings: {report.get('warnings', 0)}",
        f"Duration: {report.get('duration_ms', 0)} ms",
        "",
    ]
    mark = {"ok": "OK", "warn": "WARN", "error": "ERROR"}
    for item in report.get("checks") or []:
        lines.append(f"[{mark.get(item.get('status'), 'INFO')}] {item.get('name')}: {item.get('message')}")
    return "\n".join(lines)


def write_health_report(app, report):
    json_path, text_path = health_report_paths(app)
    tmp = json_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, json_path)
    with open(text_path, "w", encoding="utf-8") as fh:
        fh.write(format_health_report(report))
    return text_path


def read_last_health_report(app):
    json_path, _text_path = health_report_paths(app)
    if not os.path.isfile(json_path):
        return None
    try:
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None
