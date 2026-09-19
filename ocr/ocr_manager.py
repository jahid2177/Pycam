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
    MixedRecognizer,
    bengali_ocr_status,
    mixed_ocr_status,
)


DEFAULT_RECOGNIZER_FACTORIES: Dict[
    str,
    Callable,
] = {
    "english": EnglishRecognizer,
    "bengali": BengaliRecognizer,
    "mixed": MixedRecognizer,
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

    if language == "mixed":
        return mixed_ocr_status()

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



def clean_ocr_text(text: str) -> str:
    """Lightweight OCR cleanup without changing the words themselves."""
    import re
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    out = []
    blank = False
    for line in lines:
        if not line:
            if out and not blank:
                out.append("")
            blank = True
            continue
        out.append(line)
        blank = False
    return "\n".join(out).strip()



def normalize_ocr_paragraphs(text: str) -> str:
    """Clean OCR spacing and rebuild conservative paragraphs."""
    import re
    text = clean_ocr_text(text)
    if not text:
        return ""

    paragraphs = []
    for block in re.split(r"\n\s*\n", text):
        raw_lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not raw_lines:
            continue
        out = []
        for line in raw_lines:
            is_list = bool(re.match(r"^(?:[-•*]|\d+[.)]|[A-Za-z][.)])\s+", line))
            if is_list:
                if out:
                    paragraphs.append(" ".join(out))
                    out = []
                paragraphs.append(line)
                continue
            if out and re.search(r"[.!?:;।]$", out[-1]):
                paragraphs.append(" ".join(out))
                out = [line]
            else:
                out.append(line)
        if out:
            paragraphs.append(" ".join(out))
    return "\n\n".join(paragraphs).strip()


def find_text_matches(text: str, query: str, case_sensitive: bool = False):
    """Return non-overlapping (start, end) matches for OCR result search."""
    if not query:
        return []
    haystack = text or ""
    needle = query
    if not case_sensitive:
        haystack = haystack.casefold()
        needle = needle.casefold()
    matches = []
    start = 0
    while True:
        pos = haystack.find(needle, start)
        if pos < 0:
            break
        matches.append((pos, pos + len(needle)))
        start = pos + max(1, len(needle))
    return matches


def replace_ocr_text(text: str, find: str, replacement: str, case_sensitive: bool = False):
    """Replace OCR text and return (new_text, replacement_count)."""
    import re
    if not find:
        return text or "", 0
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(re.escape(find), flags)
    return pattern.subn(lambda _m: replacement, text or "")

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
        in {"bengali", "mixed"}
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


def run_ocr_with_fallback(page_paths, preferred_language="english"):
    """Run OCR with a conservative language fallback.

    Bengali is attempted only when its native backend/data is available. If
    that capability is missing or it returns no text, English ML Kit is used
    instead. A normal English request is not duplicated.

    Returns ``(text, language_used)``.
    """
    preferred = (preferred_language or "english").strip().lower()
    if preferred not in {"english", "bengali", "mixed"}:
        preferred = "english"

    if preferred == "mixed":
        available, _message = ocr_language_status("mixed")
        if available:
            try:
                text = (run_ocr_for_pages(page_paths, "mixed") or "").strip()
                if text:
                    return text, "mixed"
            except Exception:
                pass
        # If the mixed pack is unavailable, Bengali can still be attempted
        # before the final English ML Kit fallback.
        preferred = "bengali"

    if preferred == "bengali":
        available, _message = ocr_language_status("bengali")
        if available:
            try:
                text = (run_ocr_for_pages(page_paths, "bengali") or "").strip()
                if text:
                    return text, "bengali"
            except Exception:
                # The fallback exists for capability/runtime differences
                # across Android builds. The English attempt below still
                # reports its own error if the OCR stack itself is broken.
                pass

    text = (run_ocr_for_pages(page_paths, "english") or "").strip()
    return text, "english"


def run_ocr_for_individual_images(page_paths, language, recognizer_factories=None):
    """OCR a list of images with one recognizer session and return one string per image.

    Unlike ``run_ocr_for_pages``, this function preserves one output slot for
    every input image, which is useful for table-cell OCR.
    """
    normalized = (language or "english").strip().lower()
    factories = recognizer_factories or DEFAULT_RECOGNIZER_FACTORIES
    factory = factories.get(normalized)
    if factory is None:
        raise ValueError(f"Unsupported OCR language: {language!r}")
    if recognizer_factories is None and normalized in {"bengali", "mixed"}:
        available, message = ocr_language_status(normalized)
        if not available:
            raise RuntimeError(message)
    valid = [(idx, p) for idx, p in enumerate(page_paths or []) if p and os.path.isfile(p)]
    results = [""] * len(page_paths or [])
    if not valid:
        return results
    with factory() as recognizer:
        for idx, path in valid:
            try:
                results[idx] = (_recognize_best_variant(recognizer, path) or "").strip()
            except Exception:
                results[idx] = ""
    return results
