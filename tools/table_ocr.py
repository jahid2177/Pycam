"""Table detection/OCR helpers for image-to-spreadsheet workflows.

The detector prefers ruled/grid tables. When a visible grid is not present,
callers can fall back to text-to-table parsing after ordinary OCR.
"""
from __future__ import annotations

import csv
import os
import re
import tempfile
from typing import Callable, Iterable, List, Sequence, Tuple

import cv2
import numpy as np


def _cluster(values: Sequence[int], tolerance: int = 8) -> List[int]:
    vals = sorted(int(v) for v in values)
    if not vals:
        return []
    groups = [[vals[0]]]
    for v in vals[1:]:
        if abs(v - groups[-1][-1]) <= tolerance:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [int(round(sum(g) / len(g))) for g in groups]


def detect_table_grid(image_path: str) -> Tuple[List[int], List[int]]:
    """Return clustered vertical/horizontal grid coordinates.

    A usable table requires at least 2 columns and 2 rows, therefore at least
    three vertical and three horizontal boundary lines.
    """
    gray = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise RuntimeError("Could not decode the selected table image.")
    h, w = gray.shape[:2]
    scale = max(1.0, max(h, w) / 1800.0)
    if scale > 1.25:
        gray = cv2.resize(gray, (int(w / scale), int(h / scale)), interpolation=cv2.INTER_AREA)
        h, w = gray.shape[:2]

    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    bw = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12
    )

    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(18, w // 24), 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(18, h // 24)))
    horizontal = cv2.morphologyEx(bw, cv2.MORPH_OPEN, h_kernel)
    vertical = cv2.morphologyEx(bw, cv2.MORPH_OPEN, v_kernel)

    # Slight dilation reconnects broken printed table rules.
    horizontal = cv2.dilate(horizontal, np.ones((1, 3), np.uint8), iterations=1)
    vertical = cv2.dilate(vertical, np.ones((3, 1), np.uint8), iterations=1)

    ys = []
    contours, _ = cv2.findContours(horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw >= w * 0.22 and ch <= max(18, h * 0.03):
            ys.append(y + ch // 2)

    xs = []
    contours, _ = cv2.findContours(vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        if ch >= h * 0.20 and cw <= max(18, w * 0.03):
            xs.append(x + cw // 2)

    tol = max(5, int(min(h, w) * 0.008))
    xs = _cluster(xs, tol)
    ys = _cluster(ys, tol)
    return xs, ys


def crop_grid_cells(image_path: str, padding: int = 4) -> List[List[np.ndarray]]:
    image = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("Could not decode the selected table image.")
    original_h, original_w = image.shape[:2]
    xs, ys = detect_table_grid(image_path)
    if len(xs) < 3 or len(ys) < 3:
        return []

    # detect_table_grid can downscale internally, so map coordinates back.
    max_x, max_y = max(xs), max(ys)
    sx = original_w / max(max_x + 1, original_w) if max_x >= original_w else 1.0
    sy = original_h / max(max_y + 1, original_h) if max_y >= original_h else 1.0
    if sx != 1.0:
        xs = [round(x * sx) for x in xs]
    if sy != 1.0:
        ys = [round(y * sy) for y in ys]

    cells: List[List[np.ndarray]] = []
    for r in range(len(ys) - 1):
        row = []
        y1, y2 = ys[r], ys[r + 1]
        if y2 - y1 < 12:
            continue
        for c in range(len(xs) - 1):
            x1, x2 = xs[c], xs[c + 1]
            if x2 - x1 < 12:
                row.append(np.zeros((1, 1, 3), dtype=np.uint8))
                continue
            xa = max(0, x1 + padding); xb = min(original_w, x2 - padding)
            ya = max(0, y1 + padding); yb = min(original_h, y2 - padding)
            row.append(image[ya:yb, xa:xb].copy())
        if row:
            cells.append(row)
    return cells


def parse_text_table(text: str) -> List[List[str]]:
    """Parse OCR text into rows using tabs, CSV commas, or 2+ spaces."""
    rows: List[List[str]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if "\t" in line:
            cells = [x.strip() for x in line.split("\t")]
        elif re.search(r"\s{2,}", line):
            cells = [x.strip() for x in re.split(r"\s{2,}", line)]
        elif line.count(",") >= 1:
            cells = [x.strip() for x in next(csv.reader([line]))]
        else:
            cells = [line]
        rows.append(cells)
    return rows


def table_to_tsv(rows: Sequence[Sequence[str]]) -> str:
    return "\n".join("\t".join(str(v or "").replace("\t", " ") for v in row) for row in rows)


def tsv_to_rows(text: str) -> List[List[str]]:
    rows = []
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        rows.append([cell.strip() for cell in raw.split("\t")])
    return rows


def ocr_table_cells(
    image_path: str,
    language: str,
    recognize_paths: Callable[[List[str], str], List[str]],
) -> List[List[str]]:
    """Detect grid cells, OCR them, and rebuild a 2D table.

    ``recognize_paths`` receives all temporary cell image paths at once and
    returns one text item per input path. Keeping the recognizer session outside
    this module avoids coupling OpenCV code to Android/JNI.
    """
    cells = crop_grid_cells(image_path)
    if not cells:
        return []
    paths = []
    shape = []
    with tempfile.TemporaryDirectory(prefix="pycam_table_") as tmp:
        for r, row in enumerate(cells):
            shape.append(len(row))
            for c, image in enumerate(row):
                path = os.path.join(tmp, f"cell_{r:03d}_{c:03d}.png")
                if image.size <= 3:
                    cv2.imwrite(path, np.full((16, 16, 3), 255, np.uint8))
                else:
                    cv2.imwrite(path, image)
                paths.append(path)
        texts = recognize_paths(paths, language)

    out = []
    index = 0
    for count in shape:
        row = []
        for _ in range(count):
            value = texts[index] if index < len(texts) else ""
            row.append((value or "").replace("\n", " ").strip())
            index += 1
        out.append(row)
    return out
