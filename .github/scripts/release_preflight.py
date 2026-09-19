#!/usr/bin/env python3
"""Pycam Android build preflight.

Runs before Buildozer so configuration drift is caught early. The script is
stdlib-only and intentionally avoids importing Kivy/Android modules.
"""
from __future__ import annotations

import argparse
import ast
import configparser
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_RUNTIME_FILES = (
    "main.py",
    "ui/home.py",
    "ui/scanner.py",
    "ui/editor.py",
    "ui/documents.py",
    "scanner/camera.py",
    "database/database.py",
    "storage/manager.py",
    "storage/app_version.py",
    "storage/android_compat.py",
    "ocr/ocr_manager.py",
    "ocr/tesseract_ocr.py",
    "tools/id_passport_intelligence.py",
)
REQUIRED_GRADLE_DEPS = (
    "com.google.android.gms:play-services-mlkit-text-recognition:19.0.1",
    "com.rmtheis:tess-two:9.1.0",
)
REQUIRED_BUILD_REQS = (
    "python3==3.11.5",
    "hostpython3==3.11.5",
    "kivy==2.3.0",
    "kivymd==1.2.0",
    "pyjnius",
    "numpy",
    "pillow",
    "opencv",
    "camera4kivy",
    "androidstorage4kivy",
    "reportlab",
    "pypdf",
    "qrcode",
    "pyaes==1.6.1",
)
FORBIDDEN_PERMISSIONS = ("WRITE_EXTERNAL_STORAGE", "READ_MEDIA_VIDEO", "MANAGE_EXTERNAL_STORAGE", "REQUEST_INSTALL_PACKAGES")
FORBIDDEN_WORKFLOW_MARKERS = ("android release", "assemblerelease", "app-release.apk")


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _literal_assignment(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise ValueError(f"{name} not found in {path}")


def _spec_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def run_preflight(strict_assets: bool = False) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[str] = []

    def ok(message: str) -> None:
        checks.append(message)

    def require(condition: bool, message: str) -> None:
        if condition:
            ok(message)
        else:
            errors.append(message)

    for rel in REQUIRED_RUNTIME_FILES:
        require((ROOT / rel).is_file(), f"Required runtime file: {rel}")

    spec_text = _read("buildozer.spec")
    spec = _spec_values(spec_text)
    workflow = _read(".github/workflows/build-apk.yml")
    workflow_lower = workflow.lower()

    app_version = _literal_assignment(ROOT / "storage" / "app_version.py", "APP_VERSION")
    require(spec.get("version") == app_version, f"Version match: {app_version}")

    require(spec.get("android.archs") == "arm64-v8a", "Single APK ABI is arm64-v8a")
    require(spec.get("android.api") == "33", "Android target API remains pinned to 33")
    require(spec.get("android.minapi") == "24", "Android min API remains pinned to 24")
    require(spec.get("android.ndk") == "25b", "Android NDK remains pinned to 25b")
    require(spec.get("p4a.branch") == "v2024.01.21", "python-for-android branch is pinned")
    require(spec.get("p4a.bootstrap") == "sdl2", "python-for-android bootstrap is sdl2")
    require(spec.get("p4a.hook") == "camerax_provider/gradle_options.py", "CameraX p4a hook is configured")

    build_reqs = set(_csv(spec.get("requirements", "")))
    for req in REQUIRED_BUILD_REQS:
        require(req in build_reqs, f"Build requirement present: {req}")

    include_exts = set(_csv(spec.get("source.include_exts", "")))
    require("traineddata" in include_exts, "Tesseract traineddata is included in APK sources")

    excluded = set(_csv(spec.get("source.exclude_dirs", "")))
    for required_exclusion in (".github", "tests", ".buildozer", "bin", "release", "build-debug"):
        require(required_exclusion in excluded, f"Development directory excluded: {required_exclusion}")

    permission_value = spec.get("android.permissions", "")
    permission_items = _csv(permission_value)
    permission_names = set()
    for item in permission_items:
        match = re.search(r"(?:android\.permission\.)?([A-Z_]+)", item)
        if match:
            permission_names.add(match.group(1))
    for perm in ("CAMERA", "INTERNET", "READ_EXTERNAL_STORAGE", "READ_MEDIA_IMAGES", "POST_NOTIFICATIONS", "USE_BIOMETRIC"):
        require(perm in permission_names, f"Required Android permission present: {perm}")
    require(
        re.search(r"name\s*=\s*android\.permission\.READ_EXTERNAL_STORAGE\s*;\s*maxSdkVersion\s*=\s*32", permission_value) is not None,
        "Legacy READ_EXTERNAL_STORAGE is capped at API 32",
    )
    for perm in FORBIDDEN_PERMISSIONS:
        require(perm not in permission_names, f"Obsolete/unneeded Android permission absent: {perm}")

    compat_source = _read("storage/android_compat.py")
    require("FLAG_IMMUTABLE" in compat_source and "FLAG_MUTABLE" in compat_source, "PendingIntent mutability audit is implemented")
    require("start_activity_checked" in _read("storage/android_actions.py"), "Android QR/share intents use checked launcher")
    require("start_activity_for_result_checked" in _read("storage/export_destination.py"), "Android SAF picker uses checked launcher")
    try:
        compat_path = ROOT / "storage" / "android_compat.py"
        module_spec = importlib.util.spec_from_file_location("pycam_android_compat_preflight", compat_path)
        compat_module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(compat_module)
        compat_report = compat_module.static_android_compatibility_audit(ROOT)
        require(compat_report.get("ok"), "Android 12-16 static compatibility audit passes")
        warnings.extend(compat_report.get("warnings") or [])
    except Exception as exc:
        errors.append(f"Android compatibility audit could not run: {exc}")

    gradle_deps = set(_csv(spec.get("android.gradle_dependencies", "")))
    for dep in REQUIRED_GRADLE_DEPS:
        require(dep in gradle_deps, f"Gradle OCR dependency present: {dep}")

    require("buildozer -v android debug" in workflow_lower, "Workflow builds debug APK")
    for marker in FORBIDDEN_WORKFLOW_MARKERS:
        require(marker not in workflow_lower, f"Workflow release marker absent: {marker}")
    require("release/pycam-debug.apk" in workflow_lower, "Debug APK artifact has stable name")
    require("pycam-debug.apk.sha256" in workflow_lower, "Debug APK SHA-256 artifact is generated")
    require("release/apk-abis.txt" in workflow_lower, "APK ABI audit artifact is generated")
    require("release/apk-largest-files.txt" in workflow_lower, "APK size audit artifact is generated")

    hook = ROOT / "camerax_provider" / "gradle_options.py"
    if strict_assets:
        require(hook.is_file(), "CameraX provider hook exists after fetch")
    elif not hook.is_file():
        warnings.append("CameraX provider is not present locally; CI fetches it before strict preflight.")

    model_info: dict[str, dict[str, object]] = {}
    for lang in ("eng", "ben"):
        model = ROOT / "assets" / "tessdata" / f"{lang}.traineddata"
        if model.is_file():
            size = model.stat().st_size
            digest = hashlib.sha256(model.read_bytes()).hexdigest()
            model_info[lang] = {"size": size, "sha256": digest}
            require(size > 100_000, f"OCR model {lang} is non-empty ({size} bytes)")
        elif strict_assets:
            errors.append(f"OCR model missing: assets/tessdata/{lang}.traineddata")
        else:
            warnings.append(f"OCR model {lang} is not present locally; CI downloads it before strict preflight.")

    # Host requirements are for local/tests and intentionally differ from p4a recipe names.
    req_text = _read("requirements.txt").lower()
    for marker in ("kivy==2.3.0", "kivymd==1.2.0", "pyaes==1.6.1"):
        require(marker in req_text, f"Host requirement pin present: {marker}")

    report = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks_passed": len(checks),
        "app_version": app_version,
        "android": {
            "api": spec.get("android.api"),
            "minapi": spec.get("android.minapi"),
            "ndk": spec.get("android.ndk"),
            "archs": spec.get("android.archs"),
        },
        "ocr_models": model_info,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ci", action="store_true", help="Require CI-fetched assets/hooks to exist")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    report = run_preflight(strict_assets=args.ci)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Pycam preflight: {'PASS' if report['ok'] else 'FAIL'}")
        print(f"Checks passed: {report['checks_passed']}")
        print(f"App version: {report['app_version']}")
        android = report["android"]
        print(
            "Android: API {api}, min {minapi}, NDK {ndk}, ABI {archs}".format(**android)
        )
        for warning in report["warnings"]:
            print(f"WARNING: {warning}")
        for error in report["errors"]:
            print(f"ERROR: {error}")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
