"""
Professional PDF / image export for Pycam.

Backward-compatible public APIs:
    export_to_pdf(page_paths, output_path, ...)
    export_to_image(page_paths, output_path, fmt="jpg", ...)
    export_to_images_zip(page_paths, output_zip_path, fmt="jpg", ...)

PDF supports:
- Auto, A4, Letter, Legal page size
- Auto, Portrait, Landscape orientation
- configurable margins
- High / Balanced / Small output quality
- aspect-ratio-preserving centered placement (no stretching/cropping)

Image export supports:
- JPEG quality control
- PNG compression control
"""

import io
import os
import zipfile
from typing import List, Tuple

from PIL import Image
from reportlab.lib.pagesizes import A4, LETTER, LEGAL, landscape, portrait
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


POINTS_PER_INCH = 72.0
EXPORT_DPI = 200

PAGE_SIZES = {
    "a4": A4,
    "letter": LETTER,
    "legal": LEGAL,
}

QUALITY_PRESETS = {
    "high": {
        "jpeg_quality": 94,
        "png_compress": 3,
        "max_long_edge": 3600,
    },
    "balanced": {
        "jpeg_quality": 84,
        "png_compress": 6,
        "max_long_edge": 2800,
    },
    "small": {
        "jpeg_quality": 70,
        "png_compress": 8,
        "max_long_edge": 2000,
    },
}



_SEARCH_FONT_CACHE = None


def _search_text_font(text: str) -> str:
    """Best-effort Unicode font for invisible searchable PDF text layers."""
    global _SEARCH_FONT_CACHE
    if _SEARCH_FONT_CACHE:
        return _SEARCH_FONT_CACHE

    # Plain Latin text is safest and smallest with a built-in PDF font.
    if not any(ord(ch) > 255 for ch in (text or '')):
        _SEARCH_FONT_CACHE = 'Helvetica'
        return _SEARCH_FONT_CACHE

    candidates = [
        '/system/fonts/NotoSansBengali-Regular.ttf',
        '/system/fonts/NotoSansBengaliUI-Regular.ttf',
        '/system/fonts/NotoSans-Regular.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        for path in candidates:
            if os.path.isfile(path):
                try:
                    pdfmetrics.registerFont(TTFont('PycamSearchUnicode', path))
                    _SEARCH_FONT_CACHE = 'PycamSearchUnicode'
                    return _SEARCH_FONT_CACHE
                except Exception:
                    continue
    except Exception:
        pass

    _SEARCH_FONT_CACHE = 'Helvetica'
    return _SEARCH_FONT_CACHE

def _quality_preset(name: str):
    return QUALITY_PRESETS.get(
        (name or "balanced").lower(),
        QUALITY_PRESETS["balanced"],
    )


def _page_size_for_image(
    width_px: int,
    height_px: int,
    page_size: str,
    orientation: str,
    margin_pt: float,
) -> Tuple[float, float]:
    page_size = (page_size or "auto").lower()
    orientation = (orientation or "auto").lower()
    margin_pt = max(0.0, float(margin_pt))

    if page_size == "auto":
        content_w = width_px * POINTS_PER_INCH / EXPORT_DPI
        content_h = height_px * POINTS_PER_INCH / EXPORT_DPI
        return (
            max(1.0, content_w + margin_pt * 2.0),
            max(1.0, content_h + margin_pt * 2.0),
        )

    base = PAGE_SIZES.get(page_size)
    if base is None:
        raise ValueError(
            "Unsupported PDF page size. Use Auto, A4, Letter, or Legal."
        )

    if orientation == "portrait":
        return portrait(base)

    if orientation == "landscape":
        return landscape(base)

    # Auto orientation follows the document/image orientation.
    if width_px > height_px:
        return landscape(base)

    return portrait(base)


def _resize_for_quality(
    image: Image.Image,
    quality: str,
) -> Image.Image:
    preset = _quality_preset(quality)
    max_long_edge = int(preset["max_long_edge"])

    width, height = image.size
    long_edge = max(width, height)

    if long_edge <= max_long_edge:
        return image

    scale = max_long_edge / float(long_edge)
    new_size = (
        max(1, int(round(width * scale))),
        max(1, int(round(height * scale))),
    )

    return image.resize(
        new_size,
        Image.Resampling.LANCZOS,
    )


def _pdf_image_reader(
    input_path: str,
    quality: str,
):
    """
    Prepare one RGB JPEG in memory for predictable PDF compression.

    Returns:
        (ImageReader, width_px, height_px, backing_buffer)

    The backing buffer is returned so it remains alive until drawImage is done.
    """
    preset = _quality_preset(quality)

    with Image.open(input_path) as source:
        image = source.convert("RGB")
        image = _resize_for_quality(
            image,
            quality,
        )
        width_px, height_px = image.size

        buffer = io.BytesIO()
        image.save(
            buffer,
            "JPEG",
            quality=int(preset["jpeg_quality"]),
            optimize=True,
        )

    buffer.seek(0)

    return (
        ImageReader(buffer),
        width_px,
        height_px,
        buffer,
    )


def _contain_rect(
    image_width: float,
    image_height: float,
    page_width: float,
    page_height: float,
    margin_pt: float,
) -> Tuple[float, float, float, float]:
    """
    Return x, y, width, height for aspect-ratio-preserving center fit.
    """
    margin_pt = max(
        0.0,
        float(margin_pt),
    )

    available_w = max(
        1.0,
        page_width - margin_pt * 2.0,
    )
    available_h = max(
        1.0,
        page_height - margin_pt * 2.0,
    )

    scale = min(
        available_w / max(image_width, 1.0),
        available_h / max(image_height, 1.0),
    )

    draw_w = image_width * scale
    draw_h = image_height * scale

    x = (
        page_width - draw_w
    ) / 2.0
    y = (
        page_height - draw_h
    ) / 2.0

    return (
        x,
        y,
        draw_w,
        draw_h,
    )


def export_to_pdf(
    page_paths: List[str],
    output_path: str,
    page_size: str = "auto",
    orientation: str = "auto",
    margin_pt: float = 0.0,
    quality: str = "balanced",
    searchable: bool = False,
    ocr_language: str = "english",
) -> str:
    """
    Export ordered page images into one PDF.

    page_size:
        "auto" | "a4" | "letter" | "legal"

    orientation:
        "auto" | "portrait" | "landscape"

    margin_pt:
        PDF points. 72 points = 1 inch.

    quality:
        "high" | "balanced" | "small"

    No input image is stretched or cropped.
    """
    if not page_paths:
        raise ValueError(
            "No pages to export"
        )

    pdf_canvas = None

    try:
        for path in page_paths:
            searchable_text = ""
            if searchable:
                try:
                    from ocr.ocr_manager import run_ocr_for_pages, clean_ocr_text
                    searchable_text = clean_ocr_text(run_ocr_for_pages([path], ocr_language))
                except Exception:
                    searchable_text = ""
            (
                image_reader,
                width_px,
                height_px,
                backing_buffer,
            ) = _pdf_image_reader(
                path,
                quality,
            )

            pdf_page_w, pdf_page_h = _page_size_for_image(
                width_px,
                height_px,
                page_size,
                orientation,
                margin_pt,
            )

            if pdf_canvas is None:
                pdf_canvas = canvas.Canvas(
                    output_path,
                    pagesize=(
                        pdf_page_w,
                        pdf_page_h,
                    ),
                    pageCompression=1,
                )
            else:
                pdf_canvas.setPageSize(
                    (
                        pdf_page_w,
                        pdf_page_h,
                    )
                )

            # Auto pages are already derived from image dimensions at
            # EXPORT_DPI. Fixed paper sizes simply contain the image.
            if (page_size or "auto").lower() == "auto":
                image_w_pt = (
                    width_px
                    * POINTS_PER_INCH
                    / EXPORT_DPI
                )
                image_h_pt = (
                    height_px
                    * POINTS_PER_INCH
                    / EXPORT_DPI
                )
            else:
                # Only the ratio matters to _contain_rect.
                image_w_pt = float(width_px)
                image_h_pt = float(height_px)

            x, y, draw_w, draw_h = _contain_rect(
                image_w_pt,
                image_h_pt,
                pdf_page_w,
                pdf_page_h,
                margin_pt,
            )

            pdf_canvas.drawImage(
                image_reader,
                x,
                y,
                width=draw_w,
                height=draw_h,
                preserveAspectRatio=True,
                anchor="c",
            )

            # Searchable PDF: add an invisible OCR text layer.  We do not
            # have word-level bounding boxes from every OCR backend, so this
            # layer is intentionally non-visual but still searchable/selectable.
            if searchable_text:
                try:
                    text_obj = pdf_canvas.beginText()
                    top_y = max(margin_pt + 8.0, pdf_page_h - max(margin_pt, 4.0) - 10.0)
                    text_obj.setTextOrigin(max(margin_pt, 4.0), top_y)
                    font_name = _search_text_font(searchable_text)
                    text_obj.setFont(font_name, 7)
                    text_obj.setLeading(8.5)
                    if hasattr(text_obj, "setTextRenderMode"):
                        text_obj.setTextRenderMode(3)  # invisible
                    for raw_line in searchable_text.splitlines():
                        line = raw_line.strip()
                        if not line:
                            continue
                        # Keep very long OCR lines bounded; ReportLab textLine
                        # handles the reading order while the layer stays hidden.
                        for start in range(0, len(line), 180):
                            chunk = line[start:start + 180]
                            try:
                                text_obj.textLine(chunk)
                            except Exception:
                                # Built-in Helvetica cannot encode every script.
                                # If no Unicode system font is present, skip only
                                # the unencodable chunk rather than failing export.
                                continue
                    pdf_canvas.drawText(text_obj)
                except Exception:
                    pass

            # Keep buffer alive through drawImage/showPage.
            _ = backing_buffer

            pdf_canvas.showPage()

        pdf_canvas.save()
        return output_path

    except Exception:
        if pdf_canvas is not None:
            try:
                pdf_canvas.save()
            except Exception:
                pass
        raise


def _convert_image(
    input_path: str,
    output_path: str,
    fmt: str,
    quality: str = "balanced",
):
    preset = _quality_preset(
        quality
    )

    with Image.open(input_path) as source:
        image = _resize_for_quality(
            source,
            quality,
        )

        if fmt == "jpg":
            image.convert("RGB").save(
                output_path,
                "JPEG",
                quality=int(
                    preset["jpeg_quality"]
                ),
                optimize=True,
            )
            return

        if fmt == "png":
            image.save(
                output_path,
                "PNG",
                compress_level=int(
                    preset["png_compress"]
                ),
                optimize=True,
            )
            return

        raise ValueError(
            f"Unsupported image export format: {fmt!r}"
        )


def export_to_image(
    page_paths: List[str],
    output_path: str,
    fmt: str = "jpg",
    quality: str = "balanced",
    searchable: bool = False,
    ocr_language: str = "english",
) -> str:
    if not page_paths:
        raise ValueError(
            "No pages to export"
        )

    _convert_image(
        page_paths[0],
        output_path,
        fmt,
        quality=quality,
    )

    return output_path


def export_to_images_zip(
    page_paths: List[str],
    output_zip_path: str,
    fmt: str = "jpg",
    quality: str = "balanced",
    searchable: bool = False,
    ocr_language: str = "english",
) -> str:
    if not page_paths:
        raise ValueError(
            "No pages to export"
        )

    ext = (
        "jpg"
        if fmt == "jpg"
        else "png"
    )

    with zipfile.ZipFile(
        output_zip_path,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as zf:
        for index, path in enumerate(
            page_paths,
            start=1,
        ):
            tmp_path = (
                f"{output_zip_path}."
                f"page{index}.{ext}"
            )

            try:
                _convert_image(
                    path,
                    tmp_path,
                    fmt,
                    quality=quality,
                )

                zf.write(
                    tmp_path,
                    arcname=(
                        f"page_{index:02d}.{ext}"
                    ),
                )
            finally:
                if os.path.isfile(
                    tmp_path
                ):
                    os.remove(
                        tmp_path
                    )

    return output_zip_path
