"""Utilities for decoding QR codes and 1D/2D barcodes from an image.

The implementation is intentionally defensive because python-for-android/OpenCV
builds do not all expose the same barcode APIs. QR decoding is always attempted;
``cv2.barcode_BarcodeDetector`` is used when available.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np


@dataclass(frozen=True)
class CodeResult:
    value: str
    symbology: str


def classify_payload(value: str, fallback: str = "Code") -> str:
    """Classify QR payload semantics without changing the barcode symbology."""
    v = (value or "").strip()
    u = v.upper()
    if v.startswith(("http://", "https://")):
        return "URL"
    if u.startswith("WIFI:"):
        return "Wi-Fi"
    if u.startswith(("BEGIN:VCARD", "MECARD:")):
        return "Contact"
    if u.startswith(("SMSTO:", "SMS:")):
        return "SMS"
    if u.startswith("TEL:"):
        return "Phone"
    if u.startswith(("MAILTO:", "MATMSG:")):
        return "Email"
    return fallback


def _append_unique(out: List[CodeResult], value: str, symbology: str) -> None:
    value = (value or "").strip()
    if not value:
        return
    for item in out:
        if item.value == value:
            return
    out.append(CodeResult(value=value, symbology=(symbology or "Code").strip() or "Code"))


def _decode_qr(image: np.ndarray, out: List[CodeResult]) -> None:
    detector = cv2.QRCodeDetector()

    try:
        ok, decoded_info, _points, _straight = detector.detectAndDecodeMulti(image)
        if ok:
            for value in decoded_info or []:
                _append_unique(out, value, "QR")
    except Exception:
        pass

    if out:
        return

    try:
        value, _points, _straight = detector.detectAndDecode(image)
        _append_unique(out, value, "QR")
    except Exception:
        pass


def _normalize_type(raw_type: object) -> str:
    if raw_type is None:
        return "Barcode"
    value = str(raw_type).strip()
    if not value:
        return "Barcode"
    # Some OpenCV builds return enum-like names.
    value = value.replace("BARCODE_", "").replace("BarcodeType.", "")
    return value


def _decode_barcodes(image: np.ndarray, out: List[CodeResult]) -> None:
    factory = getattr(cv2, "barcode_BarcodeDetector", None)
    if factory is None:
        return

    try:
        detector = factory()
    except Exception:
        return

    # API variants seen across OpenCV releases:
    #  - detectAndDecodeWithType -> (ok, decoded_info, decoded_type, points)
    #  - detectAndDecode -> (decoded_info, decoded_type, points)
    #  - detectAndDecode -> (decoded_info, points)
    methods = []
    if hasattr(detector, "detectAndDecodeWithType"):
        methods.append(detector.detectAndDecodeWithType)
    if hasattr(detector, "detectAndDecode"):
        methods.append(detector.detectAndDecode)

    for method in methods:
        try:
            result = method(image)
        except Exception:
            continue

        if not isinstance(result, tuple):
            continue

        values = None
        types = None

        if len(result) >= 4 and isinstance(result[0], (bool, np.bool_)):
            ok, values, types = result[0], result[1], result[2]
            if not ok:
                continue
        elif len(result) >= 3:
            values, types = result[0], result[1]
        elif len(result) >= 2:
            values = result[0]

        if isinstance(values, str):
            values = [values]
        if isinstance(types, str):
            types = [types]
        if values is None:
            continue

        try:
            values_list = list(values)
        except TypeError:
            values_list = [values]

        try:
            types_list = list(types) if types is not None else []
        except TypeError:
            types_list = [types]

        for index, value in enumerate(values_list):
            symbology = _normalize_type(types_list[index] if index < len(types_list) else None)
            _append_unique(out, str(value), symbology)

        if out:
            return


def decode_codes(image: np.ndarray) -> List[CodeResult]:
    """Decode QR and supported barcodes from a BGR/gray OpenCV image."""
    if image is None or not isinstance(image, np.ndarray) or image.size == 0:
        raise ValueError("A non-empty OpenCV image is required.")

    out: List[CodeResult] = []
    _decode_qr(image, out)
    _decode_barcodes(image, out)
    return out
