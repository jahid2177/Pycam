"""
Turning a document's saved page images into an actual file the user
can keep or send somewhere - the last step in the capture pipeline.

Three export shapes:
  - PDF: one multi-page PDF, each page sized to match that image's own
    aspect ratio (rather than forcing every page onto a fixed A4/Letter
    box, which would letterbox or crop pages that don't match that
    ratio - not a great fit for photographed documents/ID cards/receipts
    of all different shapes).
  - Single image (JPG/PNG): only sensible for a one-page document -
    just re-encodes that page into the requested format.
  - Multiple images (JPG/PNG): zipped into one file, since "here are
    12 loose files" is a worse experience on mobile than one archive.

Pure OpenCV/PIL/reportlab/zipfile - no Kivy dependency, testable with
plain image files and no app running. OS-level share-sheet integration
(so exporting can hand the file straight to another app) is step 14's
job - this module only produces the file and returns its path.
"""

import os
import zipfile
from typing import List

from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

POINTS_PER_INCH = 72.0
EXPORT_DPI = 200  # assumed resolution for translating page pixel size to PDF point size


def export_to_pdf(page_paths: List[str], output_path: str) -> str:
    """Write `page_paths` (in order) into one multi-page PDF at
    `output_path`. Each PDF page is sized to that image's own aspect
    ratio at EXPORT_DPI, so a portrait ID card and a landscape receipt
    in the same document each render without distortion."""
    if not page_paths:
        raise ValueError("No pages to export")

    pdf_canvas = None
    for path in page_paths:
        with Image.open(path) as img:
            width_px, height_px = img.size
        width_pt = width_px * POINTS_PER_INCH / EXPORT_DPI
        height_pt = height_px * POINTS_PER_INCH / EXPORT_DPI

        if pdf_canvas is None:
            pdf_canvas = canvas.Canvas(output_path, pagesize=(width_pt, height_pt))
        else:
            pdf_canvas.setPageSize((width_pt, height_pt))

        pdf_canvas.drawImage(
            ImageReader(path), 0, 0, width=width_pt, height=height_pt
        )
        pdf_canvas.showPage()

    pdf_canvas.save()
    return output_path


def _convert_image(input_path: str, output_path: str, fmt: str):
    """Re-encode one page into the requested format. Goes through PIL
    (not cv2.imwrite) so format-specific quirks - e.g. PNG has no
    "quality" concept, JPEG has no alpha channel - are handled by a
    library that already knows the rules, rather than us special-casing
    each format ourselves."""
    with Image.open(input_path) as img:
        if fmt == "jpg":
            img.convert("RGB").save(output_path, "JPEG", quality=92)
        elif fmt == "png":
            img.save(output_path, "PNG")
        else:
            raise ValueError(f"Unsupported image export format: {fmt!r}")


def export_to_image(page_paths: List[str], output_path: str, fmt: str = "jpg") -> str:
    """Export a SINGLE page as a standalone image file. Only meaningful
    for a one-page document - callers should route multi-page documents
    to export_to_images_zip instead."""
    if not page_paths:
        raise ValueError("No pages to export")
    _convert_image(page_paths[0], output_path, fmt)
    return output_path


def export_to_images_zip(page_paths: List[str], output_zip_path: str, fmt: str = "jpg") -> str:
    """Export every page as an individually-numbered image, bundled
    into one zip file (so the user gets one file to keep/share instead
    of N loose ones)."""
    if not page_paths:
        raise ValueError("No pages to export")

    ext = "jpg" if fmt == "jpg" else "png"
    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, path in enumerate(page_paths, start=1):
            tmp_path = f"{output_zip_path}.page{i}.{ext}"
            _convert_image(path, tmp_path, fmt)
            zf.write(tmp_path, arcname=f"page_{i:02d}.{ext}")
            os.remove(tmp_path)

    return output_zip_path
