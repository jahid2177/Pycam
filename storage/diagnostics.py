"""Lightweight diagnostics helpers for Pycam.

No document paths/content are recorded here. The goal is to make crash reports
useful while avoiding sensitive scan data.
"""
from __future__ import annotations

import os
import platform as py_platform
from datetime import datetime


def _safe(value, fallback="unknown"):
    try:
        text = str(value)
        return text if text else fallback
    except Exception:
        return fallback


def read_app_version(base_dir: str) -> str:
    path = os.path.join(base_dir, "buildozer.spec")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped.startswith("version") and "=" in stripped:
                    return stripped.split("=", 1)[1].strip() or "unknown"
    except OSError:
        pass
    return "unknown"


def device_info() -> dict:
    info = {
        "platform": _safe(py_platform.system()),
        "platform_release": _safe(py_platform.release()),
        "machine": _safe(py_platform.machine()),
        "python": _safe(py_platform.python_version()),
        "manufacturer": "unknown",
        "model": "unknown",
        "android_version": "unknown",
        "android_api": "unknown",
    }

    try:
        from kivy.utils import platform as kivy_platform
        if kivy_platform == "android":
            from jnius import autoclass
            Build = autoclass("android.os.Build")
            Version = autoclass("android.os.Build$VERSION")
            info.update({
                "platform": "Android",
                "manufacturer": _safe(Build.MANUFACTURER),
                "model": _safe(Build.MODEL),
                "android_version": _safe(Version.RELEASE),
                "android_api": _safe(Version.SDK_INT),
            })
    except Exception:
        pass

    return info


def format_diagnostics(base_dir: str, last_screen: str = "", last_action: str = "") -> str:
    info = device_info()
    lines = [
        "APPLICATION INFORMATION",
        "-" * 40,
        f"App version: {read_app_version(base_dir)}",
        f"Last screen: {last_screen or 'unknown'}",
        f"Last action: {last_action or 'unknown'}",
        "",
        "DEVICE INFORMATION",
        "-" * 40,
        f"Platform: {info['platform']}",
        f"Manufacturer: {info['manufacturer']}",
        f"Model: {info['model']}",
        f"Android version: {info['android_version']}",
        f"Android API: {info['android_api']}",
        f"Machine: {info['machine']}",
        f"Python: {info['python']}",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
    ]
    return "\n".join(lines)
