"""Document/image utility functions for Pycam's Tools dashboard.

These functions intentionally avoid UI dependencies so they are easy to test
and can run on worker threads.  Android-native PDF rendering is delegated to
storage.file_picker.render_pdf_to_images; pure-Python PDF editing uses pypdf.
"""

import csv
import html
import io
import os
import re
import zipfile
from pathlib import Path
from typing import Iterable, List

import cv2
import numpy as np
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def _ensure_parent(path: str):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)


def _reader_writer():
    try:
        from pypdf import PdfReader, PdfWriter
        return PdfReader, PdfWriter
    except Exception as exc:
        raise RuntimeError("PDF editing support requires the pypdf package in the Android build.") from exc


def parse_page_spec(spec: str, page_count: int) -> List[int]:
    """Parse 1-based specs such as '1,3-5' into zero-based indexes."""
    spec = (spec or "").strip()
    if not spec:
        return list(range(page_count))
    result = []
    seen = set()
    for token in spec.split(','):
        token = token.strip()
        if not token:
            continue
        if '-' in token:
            left, right = token.split('-', 1)
            start, end = int(left), int(right)
            if start > end:
                start, end = end, start
            values = range(start, end + 1)
        else:
            values = [int(token)]
        for value in values:
            if value < 1 or value > page_count:
                raise ValueError(f"Page {value} is outside 1-{page_count}.")
            idx = value - 1
            if idx not in seen:
                seen.add(idx)
                result.append(idx)
    if not result:
        raise ValueError("No valid pages were selected.")
    return result


def merge_pdfs(paths: Iterable[str], output_path: str) -> str:
    PdfReader, PdfWriter = _reader_writer()
    paths = list(paths)
    if len(paths) < 2:
        raise ValueError("Select at least two PDF files.")
    writer = PdfWriter()
    for path in paths:
        reader = PdfReader(path)
        for page in reader.pages:
            writer.add_page(page)
    _ensure_parent(output_path)
    with open(output_path, 'wb') as fh:
        writer.write(fh)
    return output_path


def split_pdf(path: str, output_dir: str) -> List[str]:
    PdfReader, PdfWriter = _reader_writer()
    reader = PdfReader(path)
    os.makedirs(output_dir, exist_ok=True)
    outputs = []
    for index, page in enumerate(reader.pages, start=1):
        writer = PdfWriter()
        writer.add_page(page)
        out = os.path.join(output_dir, f"page_{index:03d}.pdf")
        with open(out, 'wb') as fh:
            writer.write(fh)
        outputs.append(out)
    return outputs


def extract_pdf_pages(path: str, output_path: str, spec: str) -> str:
    PdfReader, PdfWriter = _reader_writer()
    reader = PdfReader(path)
    indexes = parse_page_spec(spec, len(reader.pages))
    writer = PdfWriter()
    for idx in indexes:
        writer.add_page(reader.pages[idx])
    _ensure_parent(output_path)
    with open(output_path, 'wb') as fh:
        writer.write(fh)
    return output_path


def reorder_pdf_pages(path: str, output_path: str, order_spec: str) -> str:
    PdfReader, PdfWriter = _reader_writer()
    reader = PdfReader(path)
    tokens = [x.strip() for x in (order_spec or '').split(',') if x.strip()]
    if len(tokens) != len(reader.pages):
        raise ValueError(f"Enter all {len(reader.pages)} pages once, e.g. 3,1,2.")
    order = [int(x) for x in tokens]
    if sorted(order) != list(range(1, len(reader.pages) + 1)):
        raise ValueError("Page order must contain every page exactly once.")
    writer = PdfWriter()
    for value in order:
        writer.add_page(reader.pages[value - 1])
    _ensure_parent(output_path)
    with open(output_path, 'wb') as fh:
        writer.write(fh)
    return output_path


def rotate_pdf(path: str, output_path: str, angle: int = 90) -> str:
    PdfReader, PdfWriter = _reader_writer()
    angle = int(angle)
    if angle not in (90, 180, 270, -90, -180, -270):
        raise ValueError("Rotation must be 90, 180 or 270 degrees.")
    reader = PdfReader(path)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page.rotate(angle))
    _ensure_parent(output_path)
    with open(output_path, 'wb') as fh:
        writer.write(fh)
    return output_path


def lock_pdf(path: str, output_path: str, password: str) -> str:
    PdfReader, PdfWriter = _reader_writer()
    if not password:
        raise ValueError("Enter a password.")
    reader = PdfReader(path)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(password)
    _ensure_parent(output_path)
    with open(output_path, 'wb') as fh:
        writer.write(fh)
    return output_path




def unlock_pdf(path: str, output_path: str, password: str) -> str:
    PdfReader, PdfWriter = _reader_writer()
    reader = PdfReader(path)
    if reader.is_encrypted:
        if not password:
            raise ValueError("Enter the PDF password.")
        result = reader.decrypt(password)
        if not result:
            raise ValueError("Incorrect PDF password.")
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    try:
        writer.add_metadata(dict(reader.metadata or {}))
    except Exception:
        pass
    _ensure_parent(output_path)
    with open(output_path, 'wb') as fh:
        writer.write(fh)
    return output_path


def remove_pdf_pages(path: str, output_path: str, spec: str) -> str:
    PdfReader, PdfWriter = _reader_writer()
    reader = PdfReader(path)
    remove_indexes = set(parse_page_spec(spec, len(reader.pages)))
    keep = [i for i in range(len(reader.pages)) if i not in remove_indexes]
    if not keep:
        raise ValueError("You cannot remove every page from the PDF.")
    writer = PdfWriter()
    for idx in keep:
        writer.add_page(reader.pages[idx])
    _ensure_parent(output_path)
    with open(output_path, 'wb') as fh:
        writer.write(fh)
    return output_path


def insert_pdf_pages(base_path: str, insert_path: str, output_path: str, after_page: int = 0) -> str:
    PdfReader, PdfWriter = _reader_writer()
    base = PdfReader(base_path)
    extra = PdfReader(insert_path)
    if base.is_encrypted or extra.is_encrypted:
        raise ValueError("Unlock encrypted PDFs before inserting pages.")
    after_page = int(after_page)
    if after_page < 0 or after_page > len(base.pages):
        raise ValueError(f"Insert position must be between 0 and {len(base.pages)}.")
    writer = PdfWriter()
    for idx, page in enumerate(base.pages):
        if idx == after_page:
            for added in extra.pages:
                writer.add_page(added)
        writer.add_page(page)
    if after_page == len(base.pages):
        for added in extra.pages:
            writer.add_page(added)
    _ensure_parent(output_path)
    with open(output_path, 'wb') as fh:
        writer.write(fh)
    return output_path


def add_page_numbers(path: str, output_path: str, start_number: int = 1) -> str:
    PdfReader, PdfWriter = _reader_writer()
    reader = PdfReader(path)
    writer = PdfWriter()
    number = int(start_number)
    for page in reader.pages:
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)
        overlay = _page_overlay(w, h, lambda c, W, H, n=number: _draw_page_number(c, W, H, n))
        page.merge_page(PdfReader(overlay).pages[0])
        writer.add_page(page)
        number += 1
    _ensure_parent(output_path)
    with open(output_path, 'wb') as fh:
        writer.write(fh)
    return output_path


def _draw_page_number(c, w, h, number):
    c.saveState()
    c.setFont("Helvetica", 9)
    c.drawCentredString(w / 2.0, 18, str(number))
    c.restoreState()


def add_header_footer(path: str, output_path: str, header: str = "", footer: str = "") -> str:
    PdfReader, PdfWriter = _reader_writer()
    if not (header or footer):
        raise ValueError("Enter header or footer text.")
    reader = PdfReader(path)
    writer = PdfWriter()
    for page in reader.pages:
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)
        overlay = _page_overlay(w, h, lambda c, W, H: _draw_header_footer(c, W, H, header, footer))
        page.merge_page(PdfReader(overlay).pages[0])
        writer.add_page(page)
    _ensure_parent(output_path)
    with open(output_path, 'wb') as fh:
        writer.write(fh)
    return output_path


def _draw_header_footer(c, w, h, header, footer):
    c.saveState()
    c.setFont("Helvetica", 8)
    if header:
        c.drawCentredString(w / 2.0, max(18, h - 20), str(header)[:180])
    if footer:
        c.drawCentredString(w / 2.0, 18, str(footer)[:180])
    c.restoreState()


def parse_metadata_text(text: str) -> dict:
    mapping = {
        "title": "/Title", "author": "/Author", "subject": "/Subject",
        "keywords": "/Keywords", "creator": "/Creator", "producer": "/Producer",
    }
    metadata = {}
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        if "=" not in raw:
            raise ValueError("Metadata lines must use Key=Value format.")
        key, value = raw.split("=", 1)
        pdf_key = mapping.get(key.strip().lower())
        if not pdf_key:
            raise ValueError(f"Unsupported metadata key: {key.strip()}")
        metadata[pdf_key] = value.strip()
    if not metadata:
        raise ValueError("Enter at least one metadata line.")
    return metadata


def edit_pdf_metadata(path: str, output_path: str, metadata_text: str) -> str:
    PdfReader, PdfWriter = _reader_writer()
    reader = PdfReader(path)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    current = {}
    try:
        current.update(dict(reader.metadata or {}))
    except Exception:
        pass
    current.update(parse_metadata_text(metadata_text))
    writer.add_metadata(current)
    _ensure_parent(output_path)
    with open(output_path, 'wb') as fh:
        writer.write(fh)
    return output_path


def flatten_pdf(path: str, output_path: str) -> str:
    """Best-effort form flattening while keeping ordinary PDF pages intact.

    AcroForm field values are painted into page content where pypdf can
    generate an appearance. Non-form annotations are deliberately retained
    rather than deleted, because deleting them could remove visible content.
    """
    PdfReader, PdfWriter = _reader_writer()
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ValueError("Unlock the PDF before flattening it.")
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    fields = reader.get_fields() or {}
    if fields:
        values = {}
        for name, field in fields.items():
            value = field.get('/V')
            if value is not None:
                values[name] = str(value)
        if values:
            for page in writer.pages:
                try:
                    writer.update_page_form_field_values(
                        page, values, auto_regenerate=False, flatten=True
                    )
                except Exception:
                    continue
        try:
            root = writer._root_object
            if '/AcroForm' in root:
                del root['/AcroForm']
        except Exception:
            pass
    _ensure_parent(output_path)
    with open(output_path, 'wb') as fh:
        writer.write(fh)
    return output_path

def compress_pdf(path: str, output_path: str) -> str:
    PdfReader, PdfWriter = _reader_writer()
    reader = PdfReader(path)
    writer = PdfWriter()
    for page in reader.pages:
        try:
            page.compress_content_streams()
        except Exception:
            pass
        writer.add_page(page)
    try:
        writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
    except Exception:
        pass
    _ensure_parent(output_path)
    with open(output_path, 'wb') as fh:
        writer.write(fh)
    return output_path


def _page_overlay(width: float, height: float, draw_callback):
    data = io.BytesIO()
    c = canvas.Canvas(data, pagesize=(width, height))
    draw_callback(c, width, height)
    c.save()
    data.seek(0)
    return data


def watermark_pdf(path: str, output_path: str, text: str) -> str:
    PdfReader, PdfWriter = _reader_writer()
    if not (text or '').strip():
        raise ValueError("Enter watermark text.")
    reader = PdfReader(path)
    writer = PdfWriter()
    for page in reader.pages:
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)
        overlay = _page_overlay(w, h, lambda c, W, H: _draw_watermark(c, W, H, text))
        wm_page = PdfReader(overlay).pages[0]
        page.merge_page(wm_page)
        writer.add_page(page)
    _ensure_parent(output_path)
    with open(output_path, 'wb') as fh:
        writer.write(fh)
    return output_path


def _draw_watermark(c, w, h, text):
    c.saveState()
    try:
        c.setFillAlpha(0.18)
    except Exception:
        pass
    c.setFont("Helvetica-Bold", max(18, min(w, h) * 0.055))
    c.translate(w / 2.0, h / 2.0)
    c.rotate(35)
    c.drawCentredString(0, 0, str(text))
    c.restoreState()


def sign_pdf(path: str, signature_image: str, output_path: str) -> str:
    PdfReader, PdfWriter = _reader_writer()
    reader = PdfReader(path)
    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        if index == 0:
            w = float(page.mediabox.width)
            h = float(page.mediabox.height)
            overlay = _page_overlay(w, h, lambda c, W, H: _draw_signature(c, W, H, signature_image))
            sig_page = PdfReader(overlay).pages[0]
            page.merge_page(sig_page)
        writer.add_page(page)
    _ensure_parent(output_path)
    with open(output_path, 'wb') as fh:
        writer.write(fh)
    return output_path


def _draw_signature(c, w, h, signature_image):
    with Image.open(signature_image) as im:
        iw, ih = im.size
    target_w = min(w * 0.30, 180.0)
    target_h = target_w * ih / max(iw, 1)
    x = w - target_w - 36
    y = 36
    c.drawImage(ImageReader(signature_image), x, y, target_w, target_h, mask='auto', preserveAspectRatio=True)


def _text_pdf_font(text: str) -> str:
    if not any(ord(ch) > 255 for ch in (text or '')):
        return 'Helvetica'
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
                    pdfmetrics.registerFont(TTFont('PycamTextUnicode', path))
                    return 'PycamTextUnicode'
                except Exception:
                    continue
    except Exception:
        pass
    return 'Helvetica'


def text_to_pdf(text: str, output_path: str) -> str:
    text = text or ''
    _ensure_parent(output_path)
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    margin = 42
    y = height - margin
    font_name = _text_pdf_font(text)
    c.setFont(font_name, 11)

    for para in text.splitlines() or ['']:
        words = para.split(' ')
        line = ''
        for word in words:
            candidate = (line + ' ' + word).strip()
            try:
                candidate_w = c.stringWidth(candidate, font_name, 11)
            except Exception:
                candidate_w = len(candidate) * 6.0
            if candidate_w > width - margin * 2 and line:
                try:
                    c.drawString(margin, y, line)
                except Exception:
                    c.drawString(margin, y, line.encode('ascii', 'ignore').decode('ascii'))
                y -= 16
                line = word
            else:
                line = candidate
            if y < margin:
                c.showPage(); c.setFont(font_name, 11); y = height - margin
        try:
            c.drawString(margin, y, line)
        except Exception:
            c.drawString(margin, y, line.encode('ascii', 'ignore').decode('ascii'))
        y -= 18
        if y < margin:
            c.showPage(); c.setFont(font_name, 11); y = height - margin
    c.save()
    return output_path




def extract_pdf_text(path: str) -> list[str]:
    """Extract text page-by-page from a PDF.

    Returns one string per page. Encrypted PDFs must be unlocked first.
    """
    PdfReader, _ = _reader_writer()
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ValueError("Unlock the PDF before converting it to Word.")
    pages = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append(text.strip())
    return pages


def create_docx_from_pages(pages: Iterable[str], output_path: str, title: str = "") -> str:
    """Create DOCX from page text while preserving page boundaries.

    Page text is passed through the same conservative heading/bullet heuristics
    used by create_docx_from_text. A page break separates source PDF pages.
    """
    _ensure_parent(output_path)
    pages = list(pages)
    combined = []
    if title:
        combined.append(title.strip())
        combined.append("")
    for i, page_text in enumerate(pages):
        if i:
            combined.append("\f")
        combined.extend((page_text or "").splitlines())

    def paragraph_xml(raw: str) -> str:
        if raw == "\f":
            return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
        line = (raw or '').strip()
        if not line:
            return '<w:p/>'
        bullet = re.match(r'^(?:[-•*]|\d+[.)])\s+(.*)$', line)
        safe_text = html.escape(bullet.group(1) if bullet else line)
        is_heading = (
            not bullet and len(line) <= 80 and len(line.split()) <= 10 and
            (line.isupper() or (line == line.title() and not line.endswith(('.', ',', ';', ':', '।'))))
        )
        if bullet:
            ppr = '<w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr>'
            run = '<w:r><w:t xml:space="preserve">• ' + safe_text + '</w:t></w:r>'
        elif is_heading:
            ppr = '<w:pPr><w:spacing w:before="180" w:after="90"/></w:pPr>'
            run = ('<w:r><w:rPr><w:b/><w:sz w:val="28"/></w:rPr>'
                   '<w:t xml:space="preserve">' + safe_text + '</w:t></w:r>')
        else:
            ppr = '<w:pPr><w:spacing w:after="80"/></w:pPr>'
            run = '<w:r><w:t xml:space="preserve">' + safe_text + '</w:t></w:r>'
        return '<w:p>' + ppr + run + '</w:p>'

    paragraphs = [paragraph_xml(line) for line in combined or ['']]
    document_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    '<w:body>' + ''.join(paragraphs) + '<w:sectPr/></w:body></w:document>')
    content_types = ('<?xml version="1.0" encoding="UTF-8"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                     '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', content_types)
        z.writestr('_rels/.rels', rels)
        z.writestr('word/document.xml', document_xml)
    return output_path

def create_docx_from_text(text: str, output_path: str) -> str:
    """Create a compact DOCX while preserving simple OCR structure.

    Heuristics intentionally stay conservative: short all-caps/title-case lines
    become headings, common bullet prefixes become Word bullet paragraphs, and
    everything else remains normal text.
    """
    _ensure_parent(output_path)

    def paragraph_xml(raw: str) -> str:
        line = (raw or '').strip()
        if not line:
            return '<w:p/>'

        bullet = re.match(r'^(?:[-•*]|\d+[.)])\s+(.*)$', line)
        safe_text = html.escape(bullet.group(1) if bullet else line)

        is_heading = (
            not bullet
            and len(line) <= 80
            and len(line.split()) <= 10
            and (
                line.isupper()
                or (line == line.title() and not line.endswith(('.', ',', ';', ':', '।')))
            )
        )

        if bullet:
            ppr = '<w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr>'
            run = '<w:r><w:t xml:space="preserve">• ' + safe_text + '</w:t></w:r>'
        elif is_heading:
            ppr = '<w:pPr><w:spacing w:before="180" w:after="90"/></w:pPr>'
            run = ('<w:r><w:rPr><w:b/><w:sz w:val="28"/></w:rPr>'
                   '<w:t xml:space="preserve">' + safe_text + '</w:t></w:r>')
        else:
            ppr = '<w:pPr><w:spacing w:after="80"/></w:pPr>'
            run = '<w:r><w:t xml:space="preserve">' + safe_text + '</w:t></w:r>'
        return '<w:p>' + ppr + run + '</w:p>'

    paragraphs = [paragraph_xml(line) for line in (text or '').splitlines() or ['']]
    document_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    '<w:body>' + ''.join(paragraphs) + '<w:sectPr/></w:body></w:document>')
    content_types = ('<?xml version="1.0" encoding="UTF-8"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                     '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', content_types)
        z.writestr('_rels/.rels', rels)
        z.writestr('word/document.xml', document_xml)
    return output_path


def _col_letter(index: int) -> str:
    value = index + 1
    result = ''
    while value:
        value, rem = divmod(value - 1, 26)
        result = chr(65 + rem) + result
    return result


def create_xlsx_from_text(text: str, output_path: str) -> str:
    """Create a simple XLSX; tab/comma separated OCR becomes columns."""
    rows = []
    for raw in (text or '').splitlines():
        if '\t' in raw:
            cells = raw.split('\t')
        elif ',' in raw:
            cells = next(csv.reader([raw]))
        else:
            cells = [raw]
        rows.append(cells)
    if not rows:
        rows = [['']]
    row_xml = []
    for r_index, row in enumerate(rows, start=1):
        cells_xml = []
        for c_index, value in enumerate(row):
            ref = f"{_col_letter(c_index)}{r_index}"
            safe = html.escape(str(value))
            cells_xml.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{safe}</t></is></c>')
        row_xml.append(f'<row r="{r_index}">' + ''.join(cells_xml) + '</row>')
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetData>' + ''.join(row_xml) + '</sheetData></worksheet>')
    content_types = ('<?xml version="1.0" encoding="UTF-8"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                     '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                     '</Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                 '</Relationships>')
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="OCR" sheetId="1" r:id="rId1"/></sheets></workbook>')
    workbook_rels = ('<?xml version="1.0" encoding="UTF-8"?>'
                     '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                     '</Relationships>')
    _ensure_parent(output_path)
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', content_types)
        z.writestr('_rels/.rels', root_rels)
        z.writestr('xl/workbook.xml', workbook)
        z.writestr('xl/_rels/workbook.xml.rels', workbook_rels)
        z.writestr('xl/worksheets/sheet1.xml', sheet)
    return output_path



def create_csv_from_rows(rows, output_path: str) -> str:
    _ensure_parent(output_path)
    with open(output_path, 'w', encoding='utf-8-sig', newline='') as fh:
        writer = csv.writer(fh)
        for row in rows or []:
            writer.writerow([str(v or '') for v in row])
    return output_path


def create_xlsx_from_rows(rows, output_path: str, sheet_name: str = "Table") -> str:
    rows = [list(row) for row in (rows or [])]
    if not rows:
        rows = [['']]
    row_xml = []
    max_cols = max(len(row) for row in rows)
    for r_index, row in enumerate(rows, start=1):
        cells_xml = []
        for c_index, value in enumerate(row):
            ref = f"{_col_letter(c_index)}{r_index}"
            safe = html.escape(str(value or ''))
            cells_xml.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{safe}</t></is></c>')
        row_xml.append(f'<row r="{r_index}">' + ''.join(cells_xml) + '</row>')
    col_xml = ''.join(f'<col min="{i}" max="{i}" width="18" customWidth="1"/>' for i in range(1, max_cols + 1))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<cols>' + col_xml + '</cols><sheetData>' + ''.join(row_xml) + '</sheetData></worksheet>')
    content_types = ('<?xml version="1.0" encoding="UTF-8"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                     '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                     '</Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                 '</Relationships>')
    safe_sheet = html.escape((sheet_name or 'Table')[:31])
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f'<sheets><sheet name="{safe_sheet}" sheetId="1" r:id="rId1"/></sheets></workbook>')
    workbook_rels = ('<?xml version="1.0" encoding="UTF-8"?>'
                     '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                     '</Relationships>')
    _ensure_parent(output_path)
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', content_types)
        z.writestr('_rels/.rels', root_rels)
        z.writestr('xl/workbook.xml', workbook)
        z.writestr('xl/_rels/workbook.xml.rels', workbook_rels)
        z.writestr('xl/worksheets/sheet1.xml', sheet)
    return output_path

def resize_image(path: str, output_path: str, width: int, height: int, keep_aspect: bool = False) -> str:
    """Resize an image with high-quality Lanczos resampling.

    When ``keep_aspect`` is True, the image is fitted inside the requested
    canvas without distortion and centered on a white background.
    """
    width, height = int(width), int(height)
    if width <= 0 or height <= 0:
        raise ValueError("Width and height must be greater than zero.")
    with Image.open(path) as im:
        src = im.convert('RGB')
        if keep_aspect:
            ratio = min(width / max(src.width, 1), height / max(src.height, 1))
            nw = max(1, round(src.width * ratio))
            nh = max(1, round(src.height * ratio))
            fitted = src.resize((nw, nh), Image.Resampling.LANCZOS)
            resized = Image.new('RGB', (width, height), 'white')
            resized.paste(fitted, ((width - nw) // 2, (height - nh) // 2))
        else:
            resized = src.resize((width, height), Image.Resampling.LANCZOS)
        _ensure_parent(output_path)
        resized.save(output_path, 'JPEG', quality=94, optimize=True)
    return output_path


def remove_background(path: str, output_path: str, background: str = "transparent") -> str:
    """Remove the dominant border/background using GrabCut with edge refinement.

    ``background`` may be ``transparent``, ``white``, ``blue`` or ``gray``.
    The operation is intentionally conservative: if foreground confidence is
    very low, it raises an error instead of exporting a nearly empty image.
    """
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("Could not decode the selected image.")
    h, w = image.shape[:2]
    if min(h, w) < 40:
        raise RuntimeError("Image is too small for background removal.")

    # Downscale only the segmentation pass on very large photos to keep Android
    # memory/CPU usage reasonable, then scale the mask back to full resolution.
    max_side = max(h, w)
    scale = 1.0 if max_side <= 1600 else 1600.0 / max_side
    if scale < 1.0:
        work = cv2.resize(image, (max(2, round(w * scale)), max(2, round(h * scale))),
                          interpolation=cv2.INTER_AREA)
    else:
        work = image
    wh, ww = work.shape[:2]

    mask = np.full((wh, ww), cv2.GC_PR_BGD, np.uint8)
    border = max(2, int(min(wh, ww) * 0.025))
    mask[:border, :] = cv2.GC_BGD
    mask[-border:, :] = cv2.GC_BGD
    mask[:, :border] = cv2.GC_BGD
    mask[:, -border:] = cv2.GC_BGD

    # Give GrabCut a gentle center-foreground prior while still allowing the
    # subject to extend near the edges.
    cy1, cy2 = int(wh * 0.16), int(wh * 0.94)
    cx1, cx2 = int(ww * 0.14), int(ww * 0.86)
    mask[cy1:cy2, cx1:cx2] = cv2.GC_PR_FGD

    bg_model = np.zeros((1, 65), np.float64)
    fg_model = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(work, mask, None, bg_model, fg_model, 5, cv2.GC_INIT_WITH_MASK)
    except cv2.error as exc:
        raise RuntimeError("Background segmentation failed for this image.") from exc

    alpha = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    if scale < 1.0:
        alpha = cv2.resize(alpha, (w, h), interpolation=cv2.INTER_LINEAR)

    # Remove isolated noise and feather the subject edge slightly.
    k = max(3, (int(min(h, w) * 0.004) | 1))
    k = min(k, 9)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_OPEN, kernel)
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, kernel)
    alpha = cv2.GaussianBlur(alpha, (5, 5), 0)

    foreground_ratio = float(np.count_nonzero(alpha > 80)) / float(h * w)
    if foreground_ratio < 0.035:
        raise RuntimeError("Could not find a clear foreground subject. Try a photo with more background contrast.")

    mode = (background or "transparent").strip().lower()
    colors = {
        "white": (255, 255, 255),
        "blue": (235, 195, 85),      # BGR, soft passport-style blue
        "gray": (232, 232, 232),
        "grey": (232, 232, 232),
    }
    if mode in {"transparent", "clear", "png"}:
        rgba = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
        rgba[:, :, 3] = alpha
        result = rgba
    elif mode in colors:
        bg = np.full_like(image, colors[mode], dtype=np.uint8)
        a = (alpha.astype(np.float32) / 255.0)[:, :, None]
        result = np.clip(image.astype(np.float32) * a + bg.astype(np.float32) * (1.0 - a), 0, 255).astype(np.uint8)
    else:
        raise ValueError("Background must be transparent, white, blue, or gray.")

    _ensure_parent(output_path)
    if not cv2.imwrite(output_path, result):
        raise RuntimeError("Could not save the background-removed image.")
    return output_path


def combine_images_vertically(
    paths: Iterable[str],
    output_path: str,
    max_width: int = 1600,
    max_segment_height: int = 28000,
    gap_px: int = 8,
) -> str:
    """Join page images vertically with Android-safe segmented output.

    Pages are normalized to a common width and streamed into one or more
    long-image segments. Segments are written to disk as soon as they are
    complete, so memory use is bounded even for large PDFs. A single segment
    is returned as an image; multiple segments are packaged into a ZIP.
    """
    paths = [str(p) for p in paths if p and os.path.isfile(p)]
    if not paths:
        raise ValueError("No images to combine.")

    max_width = max(480, min(int(max_width or 1600), 2400))
    max_segment_height = max(6000, min(int(max_segment_height or 28000), 32000))
    gap_px = max(0, min(int(gap_px or 0), 64))

    widths = []
    for path in paths:
        with Image.open(path) as im:
            widths.append(int(im.width))
    target_width = min(max(widths), max_width)

    root, ext = os.path.splitext(output_path)
    temp_dir = root + '_segments_tmp'
    os.makedirs(temp_dir, exist_ok=True)
    saved_segments = []
    segment_pages = []
    current_height = 0

    def flush_segment():
        nonlocal segment_pages, current_height
        if not segment_pages:
            return
        seg_h = sum(im.height for im in segment_pages) + gap_px * max(0, len(segment_pages) - 1)
        canvas_img = Image.new('RGB', (target_width, seg_h), 'white')
        y = 0
        try:
            for index, im in enumerate(segment_pages):
                canvas_img.paste(im, (0, y))
                y += im.height
                if index < len(segment_pages) - 1:
                    y += gap_px
            part = os.path.join(temp_dir, f'long_image_{len(saved_segments) + 1:03d}.jpg')
            canvas_img.save(part, 'JPEG', quality=92, optimize=True, progressive=True)
            saved_segments.append(part)
        finally:
            canvas_img.close()
            for im in segment_pages:
                try:
                    im.close()
                except Exception:
                    pass
            segment_pages = []
            current_height = 0

    try:
        for path in paths:
            with Image.open(path) as src:
                im = src.convert('RGB')
                if im.width != target_width:
                    new_h = max(1, round(im.height * target_width / max(im.width, 1)))
                    resized = im.resize((target_width, new_h), Image.Resampling.LANCZOS)
                    im.close()
                    im = resized
                next_height = im.height if not segment_pages else current_height + gap_px + im.height
                if segment_pages and next_height > max_segment_height:
                    flush_segment()
                    next_height = im.height
                segment_pages.append(im)
                current_height = next_height
        flush_segment()

        _ensure_parent(output_path)
        if len(saved_segments) == 1:
            source = saved_segments[0]
            if ext.lower() == '.png':
                with Image.open(source) as image:
                    image.save(output_path, 'PNG', optimize=True)
            else:
                if ext.lower() not in {'.jpg', '.jpeg'}:
                    output_path = root + '.jpg'
                os.replace(source, output_path)
                saved_segments[0] = ''
            return output_path

        zip_path = root + '.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
            for part in saved_segments:
                z.write(part, os.path.basename(part))
        return zip_path
    finally:
        for part in saved_segments:
            if part:
                try:
                    os.remove(part)
                except OSError:
                    pass
        try:
            os.rmdir(temp_dir)
        except OSError:
            pass


def create_qr(text: str, output_path: str) -> str:
    if not (text or '').strip():
        raise ValueError("Enter text or a URL for the QR code.")
    try:
        import qrcode
    except Exception as exc:
        raise RuntimeError("QR creation requires the qrcode package in the Android build.") from exc
    img = qrcode.make(text)
    _ensure_parent(output_path)
    img.save(output_path)
    return output_path



def smart_erase_image(path: str, output_path: str, strength: int = 2) -> str:
    """Best-effort cleanup for small stains, pen specks and isolated marks.

    The routine deliberately avoids large text-like components. It builds a mask
    from small high-saturation marks and tiny dark connected components, expands
    the mask slightly, then uses OpenCV inpainting to reconstruct the page from
    surrounding pixels. It is intended for scanned paper, not photographs.
    """
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("Could not decode the selected image.")
    h, w = image.shape[:2]
    if min(h, w) < 40:
        raise RuntimeError("Image is too small for Smart Erase.")

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Colored pen / stain candidates. Printed black text is excluded here.
    sat_mask = cv2.inRange(hsv, np.array([0, 65, 20], np.uint8), np.array([179, 255, 245], np.uint8))

    # Tiny dark components only. This catches dust / dots while preserving text.
    dark = cv2.threshold(gray, 85, 255, cv2.THRESH_BINARY_INV)[1]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(dark, 8)
    tiny = np.zeros_like(gray)
    image_area = h * w
    max_area = max(10, int(image_area * 0.00045))
    for idx in range(1, count):
        x, y, cw, ch, area = stats[idx]
        if 2 <= area <= max_area and max(cw, ch) <= max(24, int(min(h, w) * 0.035)):
            tiny[labels == idx] = 255

    mask = cv2.bitwise_or(sat_mask, tiny)
    k = max(1, min(5, int(strength)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k * 2 + 1, k * 2 + 1))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.dilate(mask, kernel, iterations=1)

    # Ignore suspiciously huge masks to avoid destroying document content.
    if cv2.countNonZero(mask) > image_area * 0.12:
        sat_mask = cv2.morphologyEx(sat_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = sat_mask

    result = cv2.inpaint(image, mask, 3.0, cv2.INPAINT_TELEA)
    _ensure_parent(output_path)
    if not cv2.imwrite(output_path, result, [int(cv2.IMWRITE_JPEG_QUALITY), 95]):
        raise RuntimeError("Could not save the Smart Erase result.")
    return output_path
