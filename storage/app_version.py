"""Application version metadata and lightweight idempotent migrations."""

APP_VERSION = "1.1.0"
APP_SCHEMA_VERSION = 3
BUILD_FLAVOR = "debug"

CHANGELOG = [
    "Scanner stability, stronger edge detection and Book Mode",
    "Expanded PDF/OCR/Office tools and searchable PDF",
    "Private Vault, biometric/PIN protection and backup integrity",
    "Custom export folders, diagnostics and build hardening",
]

def run_app_migrations(app):
    """Run non-destructive app-level migrations and return applied ids."""
    prefs = app.prefs
    try:
        current = int(prefs.get("app_schema_version") or 0)
    except Exception:
        current = 0
    applied = []
    # v1: normalize language/theme defaults without overwriting user choices.
    if current < 1:
        if not prefs.get("app_language"):
            prefs.set("app_language", "en")
        applied.append(1)
        current = 1
    # v2: ensure export destination always has a supported value.
    if current < 2:
        if prefs.get("export_destination") not in {"app", "downloads", "custom"}:
            prefs.set("export_destination", "app")
        applied.append(2)
        current = 2
    # v3: ask the DB layer to apply its existing additive schema migration.
    if current < 3:
        try:
            app.db.initialize()
        except Exception:
            pass
        applied.append(3)
        current = 3
    prefs.set("app_schema_version", APP_SCHEMA_VERSION)
    return applied
