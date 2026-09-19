"""Android 12-16 compatibility helpers and static runtime audit.

This module intentionally keeps Android imports inside functions so CI/unit
checks can import and run the static audit on a desktop host.
"""
from __future__ import annotations

import io
import os
import re
import tokenize
from pathlib import Path


def android_sdk_int() -> int:
    try:
        from jnius import autoclass
        return int(autoclass("android.os.Build$VERSION").SDK_INT)
    except Exception:
        return 0


def android_device_summary() -> dict:
    """Return best-effort Android runtime metadata without raising."""
    try:
        from jnius import autoclass
        Build = autoclass("android.os.Build")
        return {
            "sdk": android_sdk_int(),
            "manufacturer": str(Build.MANUFACTURER or ""),
            "model": str(Build.MODEL or ""),
            "release": str(autoclass("android.os.Build$VERSION").RELEASE or ""),
        }
    except Exception:
        return {"sdk": 0, "manufacturer": "", "model": "", "release": ""}


def _require_android_activity():
    from kivy.utils import platform
    if platform != "android":
        raise RuntimeError("This action is only available on Android.")
    from jnius import autoclass
    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    activity = PythonActivity.mActivity
    if activity is None:
        raise RuntimeError("Android activity is not available yet.")
    return activity


def _intent_is_resolvable(activity, intent) -> bool:
    """Best-effort Intent resolution check before calling startActivity."""
    try:
        pm = activity.getPackageManager()
        return intent.resolveActivity(pm) is not None
    except Exception:
        # Some chooser/provider implementations do not expose resolveActivity
        # cleanly through PyJNIus. In that case let Android attempt the launch.
        return True


def start_activity_checked(intent, unavailable_message="No compatible Android app is available for this action."):
    """Launch an Intent without propagating ActivityNotFound-style crashes."""
    activity = _require_android_activity()
    if not _intent_is_resolvable(activity, intent):
        raise RuntimeError(str(unavailable_message))
    try:
        activity.startActivity(intent)
        return True
    except Exception as exc:
        raise RuntimeError(f"Could not open this Android action: {exc}") from exc


def start_activity_for_result_checked(
    intent,
    request_code: int,
    unavailable_message="No compatible Android app is available for this action.",
):
    activity = _require_android_activity()
    if not _intent_is_resolvable(activity, intent):
        raise RuntimeError(str(unavailable_message))
    try:
        activity.startActivityForResult(intent, int(request_code))
        return True
    except Exception as exc:
        raise RuntimeError(f"Could not open this Android picker: {exc}") from exc


def _python_identifiers(path: Path) -> set[str]:
    """Collect Python identifiers while ignoring comments and string text."""
    names: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8")
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.NAME:
                names.add(tok.string)
    except Exception:
        pass
    return names


def _permission_line(spec_text: str) -> str:
    for raw in spec_text.splitlines():
        line = raw.strip()
        if line.startswith("android.permissions") and "=" in line:
            return line.split("=", 1)[1].strip()
    return ""


def static_android_compatibility_audit(base_dir) -> dict:
    """Audit source/config for common Android 12-16 crash/privacy hazards.

    This is a static check; it does not claim to emulate a real Android device.
    It is safe to call from desktop CI and from the in-app Health Check.
    """
    base = Path(base_dir)
    issues: list[str] = []
    warnings: list[str] = []
    checks: list[str] = []

    def require(condition: bool, message: str):
        if condition:
            checks.append(message)
        else:
            issues.append(message)

    spec_path = base / "buildozer.spec"
    if not spec_path.is_file():
        return {"ok": False, "issues": ["buildozer.spec is missing"], "warnings": [], "checks": []}

    spec = spec_path.read_text(encoding="utf-8")
    perms = _permission_line(spec)

    require("POST_NOTIFICATIONS" in perms, "Android 13+ notification permission declared")
    require("READ_MEDIA_IMAGES" in perms, "Android 13+ image permission declared")
    require("USE_BIOMETRIC" in perms, "Biometric permission declared")
    require("WRITE_EXTERNAL_STORAGE" not in perms, "Legacy write-storage permission absent")
    require("MANAGE_EXTERNAL_STORAGE" not in perms, "All-files storage permission absent")
    require("REQUEST_INSTALL_PACKAGES" not in perms, "Package-install permission absent")
    require(
        re.search(r"name\s*=\s*(?:android\.permission\.)?READ_EXTERNAL_STORAGE\s*;\s*maxSdkVersion\s*=\s*32", perms) is not None,
        "Legacy READ_EXTERNAL_STORAGE is capped at API 32",
    )

    notification_path = base / "storage" / "notifications.py"
    if notification_path.is_file():
        ids = _python_identifiers(notification_path)
        require("NotificationChannel" in ids, "Android 8+ notification channel is implemented")
        # If PendingIntent is ever introduced, Android 12+ requires one of the
        # mutability flags. Comments/docstrings do not count as identifiers.
        if "PendingIntent" in ids:
            require(
                "FLAG_IMMUTABLE" in ids or "FLAG_MUTABLE" in ids,
                "Every PendingIntent declares FLAG_IMMUTABLE or FLAG_MUTABLE",
            )
        else:
            checks.append("No PendingIntent is created by document notifications")
    else:
        issues.append("storage/notifications.py is missing")

    action_path = base / "storage" / "android_actions.py"
    export_path = base / "storage" / "export_destination.py"
    share_path = base / "storage" / "share.py"

    if action_path.is_file():
        text = action_path.read_text(encoding="utf-8")
        require("start_activity_checked" in text, "QR/text Android intents use checked launcher")
    else:
        issues.append("storage/android_actions.py is missing")

    if export_path.is_file():
        text = export_path.read_text(encoding="utf-8")
        for flag in (
            "FLAG_GRANT_READ_URI_PERMISSION",
            "FLAG_GRANT_WRITE_URI_PERMISSION",
            "FLAG_GRANT_PERSISTABLE_URI_PERMISSION",
        ):
            require(flag in text, f"SAF folder picker uses {flag}")
        require("start_activity_for_result_checked" in text, "SAF picker uses checked launcher")
    else:
        issues.append("storage/export_destination.py is missing")

    if share_path.is_file():
        text = share_path.read_text(encoding="utf-8")
        require("SharedStorage" in text and "ShareSheet" in text, "File sharing uses content-URI aware shared-storage bridge")
        # Avoid file:// URI exposure on Android N+.
        require("Uri.fromFile" not in text and '"file://"' not in text and "'file://'" not in text,
                "File sharing does not expose file:// URIs")
    else:
        issues.append("storage/share.py is missing")

    # Target 33 runs on Android 16, but this project is debug/private and the
    # build toolchain is deliberately pinned. Keep this as an informational
    # warning rather than silently changing p4a/NDK/API in a runtime patch.
    match = re.search(r"^android\.api\s*=\s*(\d+)\s*$", spec, re.MULTILINE)
    target_api = int(match.group(1)) if match else 0
    if target_api and target_api < 35:
        warnings.append(
            f"Target API is {target_api}. Runtime compatibility is audited, but Play distribution may require a newer target/toolchain."
        )

    return {
        "ok": not issues,
        "issues": issues,
        "warnings": warnings,
        "checks": checks,
        "checks_passed": len(checks),
        "target_api": target_api,
    }
