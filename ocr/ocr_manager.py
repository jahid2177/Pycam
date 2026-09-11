"""
Runs OCR across every page of a document and joins the results into
one text blob, which callers store via DocumentDatabase.update_ocr_text
- that's what makes the search box on Home/Documents (already querying
`WHERE name LIKE ? OR ocr_text LIKE ?` since step 1) start matching on
a document's actual content instead of just its name.

Step 14 revision: `run_ocr_for_pages` now opens exactly ONE recognizer
session per call (covering however many pages the document has) rather
than creating a fresh ML Kit client / Tesseract instance per page - see
the step 14 notes in ocr/mlkit_ocr.py and ocr/tesseract_ocr.py for why
that matters. `recognizer_factories` is a dict of
{language: zero-arg callable returning a context manager with a
.recognize(path) method} - defaulting to the real Android bridges but
overridable, which is what makes this dispatch/session/joining logic
testable without an Android device (see the project's test notes),
even though the two real backends cannot be.
"""

from typing import Callable, Dict, List, Optional

from ocr.mlkit_ocr import EnglishRecognizer
from ocr.tesseract_ocr import BengaliRecognizer

DEFAULT_RECOGNIZER_FACTORIES: Dict[str, Callable] = {
    "english": EnglishRecognizer,
    "bengali": BengaliRecognizer,
}


def run_ocr_for_pages(
    page_paths: List[str],
    language: str,
    recognizer_factories: Optional[Dict[str, Callable]] = None,
) -> str:
    """Run OCR over every page in order (one recognizer session for the
    whole call) and join the non-empty results.

    A single PAGE's failure (bad decode, timeout, whatever) is skipped
    rather than aborting the whole document - a document that gets
    partial OCR text is more useful than one that gets none because
    page 4 of 5 had a glitch. A failure creating the SESSION itself
    (missing traineddata, wrong platform, model load failure) is a
    systemic problem, not a per-page one, and propagates immediately
    rather than being retried per page or masked as "every page failed".
    """
    factories = recognizer_factories or DEFAULT_RECOGNIZER_FACTORIES
    factory = factories.get(language)
    if factory is None:
        raise ValueError(f"Unsupported OCR language: {language!r}")
    if not page_paths:
        return ""

    parts = []
    errors = []
    multi_page = len(page_paths) > 1

    with factory() as recognizer:
        for i, path in enumerate(page_paths, start=1):
            try:
                text = (recognizer.recognize(path) or "").strip()
            except Exception as e:
                errors.append(str(e))
                continue
            if text:
                parts.append(f"----- Page {i} -----\n{text}" if multi_page else text)

    if not parts and errors:
        raise RuntimeError(f"OCR failed on every page: {errors[0]}")

    return "\n\n".join(parts)
