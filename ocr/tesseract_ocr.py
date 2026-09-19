"""Tesseract OCR backends for Bengali and mixed English+Bengali text.

The Android build uses tess-two and bundled tessdata files. Capability checks
verify Android runtime, trained-data files, and native Java class availability
before a session starts.
"""

import os
from typing import Iterable, Tuple

from kivy.utils import platform

TESSERACT_AVAILABLE = platform == "android"
MIN_TRAINEDDATA_BYTES = 100_000
SUPPORTED_TESS_LANGUAGES = {
    "bengali": ("ben",),
    "mixed": ("eng", "ben"),
}


def _bundled_datapath() -> str:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, "assets") + os.sep


def _traineddata_path(code: str) -> str:
    return os.path.join(_bundled_datapath(), "tessdata", f"{code}.traineddata")


def _check_models(codes: Iterable[str]) -> Tuple[bool, str]:
    missing = []
    corrupt = []
    for code in codes:
        path = _traineddata_path(code)
        if not os.path.isfile(path):
            missing.append(os.path.basename(path))
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        if size < MIN_TRAINEDDATA_BYTES:
            corrupt.append(os.path.basename(path))

    if missing:
        return False, "OCR language data is missing: " + ", ".join(missing)
    if corrupt:
        return False, "OCR language data appears incomplete/corrupt: " + ", ".join(corrupt)
    return True, "OCR language data verified."


def tesseract_ocr_status(language: str) -> Tuple[bool, str]:
    language = (language or "").strip().lower()
    codes = SUPPORTED_TESS_LANGUAGES.get(language)
    if not codes:
        return False, f"Unsupported Tesseract OCR language: {language!r}"
    if not TESSERACT_AVAILABLE:
        return False, "This OCR mode is available only in the Android build."

    ok, message = _check_models(codes)
    if not ok:
        return False, message

    try:
        from jnius import autoclass
        autoclass("com.googlecode.tesseract.android.TessBaseAPI")
    except Exception:
        return False, (
            "Tesseract native library is not included in this APK. "
            "The Android build must include com.rmtheis:tess-two:9.1.0."
        )

    names = "+".join(codes)
    return True, f"Tesseract OCR is available ({names} models + native engine verified)."


def bengali_ocr_status() -> Tuple[bool, str]:
    return tesseract_ocr_status("bengali")


def mixed_ocr_status() -> Tuple[bool, str]:
    return tesseract_ocr_status("mixed")


class TesseractRecognizer:
    """One Tesseract instance reused across all pages of one OCR request."""

    def __init__(self, language="bengali"):
        normalized = (language or "").strip().lower()
        codes = SUPPORTED_TESS_LANGUAGES.get(normalized)
        if not codes:
            raise ValueError(f"Unsupported Tesseract OCR language: {language!r}")
        available, message = tesseract_ocr_status(normalized)
        if not available:
            raise RuntimeError(message)
        self.language = normalized
        self.language_codes = "+".join(codes)
        self._tess = None
        self._JavaFile = None

    def __enter__(self):
        from jnius import autoclass
        TessBaseAPI = autoclass("com.googlecode.tesseract.android.TessBaseAPI")
        self._JavaFile = autoclass("java.io.File")
        tess = TessBaseAPI()
        try:
            initialized = tess.init(_bundled_datapath(), self.language_codes)
        except Exception as exc:
            try:
                tess.recycle()
            except Exception:
                pass
            raise RuntimeError(
                f"Tesseract failed to initialize {self.language_codes} OCR. "
                f"Check traineddata files. Details: {exc}"
            ) from exc
        if not initialized:
            try:
                tess.recycle()
            except Exception:
                pass
            raise RuntimeError(
                f"Tesseract failed to initialize {self.language_codes} OCR. "
                "The traineddata files may be corrupt or incompatible."
            )
        self._tess = tess
        return self

    def recognize(self, image_path: str) -> str:
        if self._tess is None:
            raise RuntimeError("Tesseract OCR session is not initialized.")
        if not os.path.isfile(image_path):
            raise RuntimeError(f"OCR image not found: {image_path}")
        try:
            self._tess.setImage(self._JavaFile(image_path))
            return self._tess.getUTF8Text() or ""
        except Exception as exc:
            raise RuntimeError(f"OCR failed for image: {exc}") from exc

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._tess is not None:
            try:
                self._tess.recycle()
            finally:
                self._tess = None
        return False


class BengaliRecognizer(TesseractRecognizer):
    def __init__(self):
        super().__init__("bengali")


class MixedRecognizer(TesseractRecognizer):
    """Recognize English and Bengali together using eng+ben in one session."""
    def __init__(self):
        super().__init__("mixed")
