"""
OCR dispatcher and document-level session manager.

Existing public API remains:
    run_ocr_for_pages(page_paths, language, recognizer_factories=None) -> str

Step 9 reliability improvements:
- validate Bengali capability before starting a session;
- OCR-friendly preprocessing for each page;
- first try enhanced image;
- if enhanced OCR is very weak, retry the original image and choose the
  better text result;
- per-page failures do not abort a multi-page document;
- temporary preprocessing files are always cleaned up;
- native recognizer session is still created exactly once per document.
"""

import os
import tempfile
from typing import Callable, Dict, List, Optional

from ocr.mlkit_ocr import EnglishRecognizer
from ocr.preprocess import (
    prepare_ocr_image,
    text_quality_score,
)
from ocr.tesseract_ocr import (
    BengaliRecognizer,
    bengali_ocr_status,
)


DEFAULT_RECOGNIZER_FACTORIES: Dict[
    str,
    Callable,
] = {
    "english": EnglishRecognizer,
    "bengali": BengaliRecognizer,
}


def ocr_language_status(
    language: str,
):
    """
    Return (available, human-readable message).

    English native ML Kit class loading is validated when its recognizer
    session opens. Bengali has additional build/data requirements that can be
    checked ahead of time.
    """
    language = (
        language or ""
    ).strip().lower()

    if language == "english":
        return (
            True,
            "English OCR uses on-device Google ML Kit in the Android build.",
        )

    if language == "bengali":
        return bengali_ocr_status()

    return (
        False,
        f"Unsupported OCR language: {language!r}",
    )


def _recognize_best_variant(
    recognizer,
    original_path: str,
) -> str:
    """
    OCR the enhanced variant first. Retry original only when the first result
    is unusually weak, then select the stronger text result.
    """
    temp_path = None

    try:
        suffix = ".jpg"
        fd, temp_path = tempfile.mkstemp(
            prefix="pycam_ocr_",
            suffix=suffix,
        )
        os.close(fd)

        enhanced_path = prepare_ocr_image(
            original_path,
            temp_path,
        )

        enhanced_text = (
            recognizer.recognize(
                enhanced_path
            )
            or ""
        ).strip()

        enhanced_score = (
            text_quality_score(
                enhanced_text
            )
        )

        # Most normal pages need only one OCR pass. A weak result gets one
        # fallback on the untouched source because enhancement can occasionally
        # hurt colored/low-resolution text.
        if enhanced_score >= 24.0:
            return enhanced_text

        original_text = (
            recognizer.recognize(
                original_path
            )
            or ""
        ).strip()

        original_score = (
            text_quality_score(
                original_text
            )
        )

        if (
            original_score
            > enhanced_score
        ):
            return original_text

        return enhanced_text

    finally:
        if (
            temp_path
            and os.path.isfile(
                temp_path
            )
        ):
            try:
                os.remove(
                    temp_path
                )
            except OSError:
                pass


def run_ocr_for_pages(
    page_paths: List[str],
    language: str,
    recognizer_factories: Optional[
        Dict[str, Callable]
    ] = None,
) -> str:
    """
    Run OCR over every page in order with one native recognizer session.

    One bad page is skipped. A systemic/session problem such as missing native
    OCR dependency or Bengali trained-data propagates immediately with a clear
    message.
    """
    normalized_language = (
        language or ""
    ).strip().lower()

    factories = (
        recognizer_factories
        or DEFAULT_RECOGNIZER_FACTORIES
    )

    factory = factories.get(
        normalized_language
    )

    if factory is None:
        raise ValueError(
            "Unsupported OCR language: "
            f"{language!r}"
        )

    if not page_paths:
        return ""

    # Capability check applies to the built-in Bengali backend. Custom
    # recognizer_factories used in tests remain fully injectable.
    if (
        recognizer_factories is None
        and normalized_language
        == "bengali"
    ):
        available, message = (
            ocr_language_status(
                normalized_language
            )
        )

        if not available:
            raise RuntimeError(
                message
            )

    valid_paths = []

    for path in page_paths:
        if (
            path
            and os.path.isfile(path)
        ):
            valid_paths.append(
                path
            )

    if not valid_paths:
        raise RuntimeError(
            "OCR could not start because none of the document pages "
            "could be read."
        )

    parts = []
    errors = []
    multi_page = (
        len(valid_paths) > 1
    )

    # Session construction errors deliberately propagate. These indicate a
    # missing model/native dependency and retrying every page cannot fix them.
    with factory() as recognizer:
        for index, path in enumerate(
            valid_paths,
            start=1,
        ):
            try:
                text = (
                    _recognize_best_variant(
                        recognizer,
                        path,
                    )
                    or ""
                ).strip()
            except Exception as exc:
                errors.append(
                    f"Page {index}: {exc}"
                )
                continue

            if not text:
                continue

            if multi_page:
                parts.append(
                    "----- Page "
                    f"{index} -----\n"
                    f"{text}"
                )
            else:
                parts.append(
                    text
                )

    if not parts:
        if errors:
            raise RuntimeError(
                "OCR could not recognize any page. "
                f"{errors[0]}"
            )

        return ""

    return "\n\n".join(
        parts
    )
