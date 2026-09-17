"""
Bengali OCR via Tesseract4Android.

Bengali is NOT claimed as available merely because this Python file exists.
Before recognition, Pycam validates:
1. Android runtime;
2. assets/tessdata/ben.traineddata exists and looks non-empty;
3. the Tesseract4Android Java class is actually packaged in the APK.

This is important because the current project may intentionally omit either
the large Bengali trained-data file or the native dependency to preserve a
known-good build.

Public helpers:
    bengali_ocr_status() -> (available: bool, message: str)
    BengaliRecognizer context manager
"""

import os
from typing import Tuple

from kivy.utils import platform


TESSERACT_AVAILABLE = (
    platform == "android"
)

TRAINEDDATA_DOWNLOAD_URL = (
    "https://github.com/tesseract-ocr/"
    "tessdata_fast/raw/main/ben.traineddata"
)

MIN_TRAINEDDATA_BYTES = 100_000


def _bundled_datapath() -> str:
    project_root = os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
    return os.path.join(
        project_root,
        "assets",
    ) + os.sep


def _traineddata_path() -> str:
    return os.path.join(
        _bundled_datapath(),
        "tessdata",
        "ben.traineddata",
    )


def bengali_ocr_status() -> Tuple[bool, str]:
    """
    Check whether Bengali OCR can actually run in this installed build.
    """
    if not TESSERACT_AVAILABLE:
        return (
            False,
            "Bengali OCR is available only in the Android build.",
        )

    traineddata = _traineddata_path()

    if not os.path.isfile(
        traineddata
    ):
        return (
            False,
            "Bengali OCR is not enabled in this build because "
            "assets/tessdata/ben.traineddata is missing.",
        )

    try:
        file_size = os.path.getsize(
            traineddata
        )
    except OSError:
        file_size = 0

    if file_size < MIN_TRAINEDDATA_BYTES:
        return (
            False,
            "Bengali OCR data appears incomplete or corrupt: "
            "assets/tessdata/ben.traineddata.",
        )

    try:
        from jnius import autoclass

        autoclass(
            "com.googlecode.tesseract.android.TessBaseAPI"
        )
    except Exception:
        return (
            False,
            "Bengali OCR native library is not included in this APK. "
            "Tesseract4Android must be packaged before Bengali OCR can run.",
        )

    return (
        True,
        "Bengali OCR is available.",
    )


class BengaliRecognizer:
    """
    One Tesseract instance reused across all pages of one OCR request.
    """

    def __init__(self):
        available, message = (
            bengali_ocr_status()
        )

        if not available:
            raise RuntimeError(
                message
            )

        self._tess = None
        self._JavaFile = None

    def __enter__(self):
        from jnius import autoclass

        TessBaseAPI = autoclass(
            "com.googlecode.tesseract.android.TessBaseAPI"
        )
        self._JavaFile = autoclass(
            "java.io.File"
        )

        tess = TessBaseAPI()

        try:
            initialized = tess.init(
                _bundled_datapath(),
                "ben",
            )
        except Exception as exc:
            try:
                tess.recycle()
            except Exception:
                pass

            raise RuntimeError(
                "Tesseract failed to initialize Bengali OCR. "
                f"Check ben.traineddata. Details: {exc}"
            ) from exc

        if not initialized:
            try:
                tess.recycle()
            except Exception:
                pass

            raise RuntimeError(
                "Tesseract failed to initialize Bengali OCR. "
                "ben.traineddata may be corrupt or incompatible."
            )

        self._tess = tess
        return self

    def recognize(
        self,
        image_path: str,
    ) -> str:
        if self._tess is None:
            raise RuntimeError(
                "Bengali OCR session is not initialized."
            )

        if not os.path.isfile(
            image_path
        ):
            raise RuntimeError(
                f"OCR image not found: {image_path}"
            )

        try:
            self._tess.setImage(
                self._JavaFile(
                    image_path
                )
            )
            text = (
                self._tess.getUTF8Text()
            )
            return text or ""
        except Exception as exc:
            raise RuntimeError(
                f"Bengali OCR failed for image: {exc}"
            ) from exc

    def __exit__(
        self,
        exc_type,
        exc_val,
        exc_tb,
    ):
        if self._tess is not None:
            try:
                self._tess.recycle()
            finally:
                self._tess = None

        return False
