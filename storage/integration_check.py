"""Fast static integration checks for Pycam.

These checks deliberately avoid importing Kivy/Android modules so they can run
on GitHub Actions before the Android toolchain is installed. They are intended
to catch cross-file wiring regressions after feature additions.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REQUIRED_DIRS = (
    "ui", "scanner", "storage", "database", "ocr", "pdf", "tools",
    "image_processing", "assets",
)


def _literal_assignment(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise ValueError(f"{name} not found in {path}")


def run_static_integration_check(base_dir: str | Path) -> dict:
    base = Path(base_dir)
    issues: list[str] = []
    warnings: list[str] = []

    for rel in REQUIRED_DIRS:
        if not (base / rel).exists():
            issues.append(f"Missing required directory: {rel}")

    # Version consistency.
    app_version = _literal_assignment(base / "storage" / "app_version.py", "APP_VERSION")
    spec_text = (base / "buildozer.spec").read_text(encoding="utf-8")
    match = re.search(r"^version\s*=\s*([^\n#]+)", spec_text, re.MULTILINE)
    spec_version = match.group(1).strip() if match else ""
    if spec_version != app_version:
        issues.append(f"Version mismatch: app={app_version}, buildozer={spec_version or 'missing'}")

    # Startup route consistency.
    lazy = _literal_assignment(base / "main.py", "_LAZY_SCREENS")
    for screen, route in lazy.items():
        module_name = route[0]
        module_path = base / (module_name.replace(".", "/") + ".py")
        if not module_path.is_file():
            issues.append(f"Lazy screen {screen} points to missing module {module_name}")

    # Workflow must build debug only and must not build a release APK.
    workflow = (base / ".github" / "workflows" / "build-apk.yml").read_text(encoding="utf-8")
    lowered = workflow.lower()
    if "android debug" not in lowered:
        issues.append("GitHub workflow does not contain Android debug build")
    release_markers = ("android release", "assembleRelease", "app-release.apk")
    if any(marker.lower() in lowered for marker in release_markers):
        issues.append("GitHub workflow still contains release APK build/output")
    if "arm64-v8a" not in spec_text:
        issues.append("arm64-v8a is not configured in buildozer.spec")

    # Core runtime files required by the primary flow.
    for rel in (
        "ui/home.py", "ui/scanner.py", "ui/editor.py", "ui/documents.py",
        "scanner/camera.py", "database/database.py", "storage/manager.py",
    ):
        if not (base / rel).is_file():
            issues.append(f"Primary-flow source missing: {rel}")

    # Development placeholders must not leak into visible tool routing.
    tools_text = (base / "ui" / "tools.py").read_text(encoding="utf-8").lower()
    for marker in ("coming soon", "not connected", "todo: connect"):
        if marker in tools_text:
            issues.append(f"Visible Tools code still contains placeholder marker: {marker}")

    return {
        "ok": not issues,
        "issues": issues,
        "warnings": warnings,
        "app_version": app_version,
        "lazy_screen_count": len(lazy),
    }
