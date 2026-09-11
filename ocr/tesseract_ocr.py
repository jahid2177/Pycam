"""
Bengali text recognition via Tesseract4Android, since Google's
on-device ML Kit does not support Bengali script at all (see
ocr/mlkit_ocr.py's docstring and this project's README for that
finding).

Requires (see buildozer.spec):
    android.gradle_repositories = https://jitpack.io
    android.gradle_dependencies = cz.adaptech.tesseract4android:tesseract4android:4.9.0

Requires a Bengali trained-data file at assets/tessdata/ben.traineddata
in this project - NOT included here, since it's a multi-megabyte binary
this environment has no network access to fetch (and fabricating a fake
one would fail silently/confusingly on-device instead of honestly). To
provide it:
    1. Download ben.traineddata from:
       https://github.com/tesseract-ocr/tessdata_fast/raw/main/ben.traineddata
       (or tessdata_best for higher accuracy / larger file size)
    2. Place it at: CamScannerPython/assets/tessdata/ben.traineddata
BengaliRecognizer fails fast with a clear message if it's missing,
rather than a cryptic native-layer crash.

Design note on why no asset-copying code is needed here: Tesseract's
TessBaseAPI.init(datapath, language) requires `datapath` to be a real,
directly-readable filesystem directory containing a `tessdata`
subfolder - it cannot read straight out of an APK's compressed assets.
A typical Android-Studio-built app has to copy its bundled asset out to
app-private storage at runtime for this reason. This project doesn't
need that step: python-for-android already extracts the whole app
source tree (including anything under source.include_exts, which
covers assets/) onto the device's real filesystem at first launch -
it's the same mechanism main.py already relies on for its icon path
(`os.path.join("assets", "icons", "app_icon.png")`). So
`assets/tessdata/ben.traineddata` already sits exactly where Tesseract's
datapath convention expects it, with nothing to copy.

Step 14 revision: the original version called `TessBaseAPI().init(...)`
- which loads the language model from disk - and `.recycle()` for
EVERY page. Tesseract4Android's own docs call this out directly:
better to create and initialize the instance once and reuse it across
multiple images. BengaliRecognizer now does exactly that: one init per
document, reused for every page, recycled once at the end.

Cannot be exercised or verified outside a real Android device/emulator,
same limitation as ocr/mlkit_ocr.py.
"""

import os

from kivy.utils import platform

TESSERACT_AVAILABLE = platform == "android"

TRAINEDDATA_DOWNLOAD_URL = (
    "https://github.com/tesseract-ocr/tessdata_fast/raw/main/ben.traineddata"
)


def _bundled_datapath() -> str:
    """Parent-of-tessdata directory Tesseract's datapath convention
    expects - this project's assets/ folder, which already contains
    assets/tessdata/ben.traineddata once that file is provided (see
    module docstring)."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, "assets") + os.sep


def _traineddata_path() -> str:
    return os.path.join(_bundled_datapath(), "tessdata", "ben.traineddata")


class BengaliRecognizer:
    """One Tesseract instance, initialized once and reused across every
    page of a document.

    Usage:
        with BengaliRecognizer() as recognizer:
            for path in page_paths:
                text = recognizer.recognize(path)
    """

    def __init__(self):
        if not TESSERACT_AVAILABLE:
            raise RuntimeError("Tesseract OCR is only available on Android")
        if not os.path.exists(_traineddata_path()):
            raise RuntimeError(
                "Bengali OCR data not found - download ben.traineddata from "
                f"{TRAINEDDATA_DOWNLOAD_URL} and place it at "
                "assets/tessdata/ben.traineddata before building."
            )
        self._tess = None
        self._JavaFile = None

    def __enter__(self):
        from jnius import autoclass

        TessBaseAPI = autoclass("com.googlecode.tesseract.android.TessBaseAPI")
        self._JavaFile = autoclass("java.io.File")

        tess = TessBaseAPI()
        if not tess.init(_bundled_datapath(), "ben"):
            raise RuntimeError(
                "Tesseract failed to initialize for Bengali - "
                "ben.traineddata may be corrupt or the wrong version"
            )
        self._tess = tess
        return self

    def recognize(self, image_path: str) -> str:
        """Run the (already-initialized) Tesseract instance on one
        page. Raises RuntimeError on any bridge failure - ocr_manager.py
        catches this per page rather than letting one bad page abort
        the whole document."""
        self._tess.setImage(self._JavaFile(image_path))
        text = self._tess.getUTF8Text()
        return text or ""

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._tess is not None:
            self._tess.recycle()
            self._tess = None
        return False
