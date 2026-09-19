"""Native Android printing helpers for Pycam.

The implementation uses Android PrintManager with a WebView-backed
PrintDocumentAdapter.  It intentionally avoids pretending that sharing a PDF
is the same as printing: on Android this opens the system print dialog where
the user can choose a printer, Save as PDF, page range, paper size, etc.
"""

import html
import os
import time
from pathlib import Path
from urllib.parse import quote

_ACTIVE_PRINT_JOBS = {}


def _assert_android():
    from kivy.utils import platform
    if platform != "android":
        raise RuntimeError("Printing is available in the Android build only.")


def _file_uri(path: str) -> str:
    absolute = os.path.abspath(path)
    if not os.path.exists(absolute):
        raise FileNotFoundError(absolute)
    # Keep '/' separators unescaped so Android WebView receives a normal file URI.
    return "file://" + quote(absolute, safe="/")


def build_print_html(image_paths, title="Pycam document"):
    """Build a print-friendly HTML document from one or more local images."""
    paths = [str(p) for p in image_paths if p]
    if not paths:
        raise ValueError("No pages were supplied for printing.")

    page_blocks = []
    for index, path in enumerate(paths):
        uri = _file_uri(path)
        last = index == len(paths) - 1
        klass = "page last" if last else "page"
        page_blocks.append(
            f'<section class="{klass}"><img src="{html.escape(uri, quote=True)}" /></section>'
        )

    safe_title = html.escape(str(title or "Pycam document"))
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{safe_title}</title>
<style>
@page {{ margin: 8mm; }}
html, body {{ margin: 0; padding: 0; background: white; }}
.page {{
  width: 100%;
  min-height: 96vh;
  display: flex;
  align-items: center;
  justify-content: center;
  page-break-after: always;
  break-after: page;
}}
.page.last {{ page-break-after: auto; break-after: auto; }}
img {{
  display: block;
  max-width: 100%;
  max-height: 96vh;
  width: auto;
  height: auto;
  object-fit: contain;
}}
</style>
</head>
<body>
{''.join(page_blocks)}
</body>
</html>"""


def print_images(image_paths, job_name="Pycam Document"):
    """Open Android's system print dialog for image pages.

    Returns a lightweight job token. The actual print/save action remains under
    user control in Android's system print UI.
    """
    _assert_android()
    paths = [os.path.abspath(str(p)) for p in image_paths if p]
    if not paths:
        raise ValueError("No printable image was selected.")
    for path in paths:
        if not os.path.isfile(path):
            raise FileNotFoundError(path)

    from kivy.clock import Clock
    from jnius import autoclass, PythonJavaClass, java_method

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    Context = autoclass("android.content.Context")
    WebView = autoclass("android.webkit.WebView")
    PrintAttributesBuilder = autoclass("android.print.PrintAttributes$Builder")
    MediaSize = autoclass("android.print.PrintAttributes$MediaSize")
    Resolution = autoclass("android.print.PrintAttributes$Resolution")
    Margins = autoclass("android.print.PrintAttributes$Margins")

    activity = PythonActivity.mActivity
    if activity is None:
        raise RuntimeError("Android activity is not available for printing.")

    token = f"print_{int(time.time() * 1000)}"
    webview = WebView(activity)
    settings = webview.getSettings()
    settings.setJavaScriptEnabled(False)
    settings.setAllowFileAccess(True)
    settings.setAllowContentAccess(True)
    try:
        settings.setBuiltInZoomControls(False)
        settings.setDisplayZoomControls(False)
    except Exception:
        pass

    html_doc = build_print_html(paths, title=job_name)
    # A local base URL keeps file:// image loading enabled for private app files.
    webview.loadDataWithBaseURL("file:///", html_doc, "text/html", "UTF-8", None)

    class _StartPrintRunnable(PythonJavaClass):
        __javainterfaces__ = ["java/lang/Runnable"]
        __javacontext__ = "app"

        @java_method("()V")
        def run(self):
            try:
                print_manager = activity.getSystemService(Context.PRINT_SERVICE)
                adapter = webview.createPrintDocumentAdapter(str(job_name or "Pycam Document"))

                # A4 is a sensible document-scanner default. Android's print UI
                # still lets the user change paper size/orientation/printer.
                attributes = (
                    PrintAttributesBuilder()
                    .setMediaSize(MediaSize.ISO_A4)
                    .setResolution(Resolution("pycam", "Pycam", 300, 300))
                    .setMinMargins(Margins.NO_MARGINS)
                    .build()
                )
                print_manager.print(str(job_name or "Pycam Document"), adapter, attributes)
            except Exception as exc:
                # Preserve an actionable error for the UI caller/diagnostics.
                _ACTIVE_PRINT_JOBS[token]["error"] = str(exc)

    runnable = _StartPrintRunnable()
    _ACTIVE_PRINT_JOBS[token] = {
        "webview": webview,
        "runnable": runnable,
        "paths": paths,
        "error": None,
    }

    # Give the WebView a short period to lay out the local HTML before Android
    # asks the adapter for printable pages. postDelayed executes on WebView's UI
    # thread, which is required by the printing APIs.
    webview.postDelayed(runnable, 900)

    def _cleanup(_dt):
        job = _ACTIVE_PRINT_JOBS.pop(token, None)
        if not job:
            return
        view = job.get("webview")
        if view is not None:
            try:
                view.stopLoading()
                view.destroy()
            except Exception:
                pass

    # Keep the WebView alive long enough for the print spooler to snapshot it.
    Clock.schedule_once(_cleanup, 300)
    return token
