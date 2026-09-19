"""Structured NID OCR parsing and passport MRZ parsing/validation.

No network or extra dependency is required. OCR itself is supplied by the
existing Pycam OCR manager; this module only parses text returned by OCR.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def _ascii_digits(text: str) -> str:
    return (text or "").translate(_BN_DIGITS)


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", (line or "").strip())


def _lines(text: str) -> List[str]:
    return [_clean_line(x) for x in (text or "").replace("\r", "\n").split("\n") if _clean_line(x)]


def _label_value(lines: List[str], labels: Tuple[str, ...]) -> str:
    labels_cf = tuple(x.casefold() for x in labels)
    for i, line in enumerate(lines):
        cf = line.casefold()
        for label, label_cf in zip(labels, labels_cf):
            if label_cf in cf:
                # Inline value after label / colon / dash.
                pos = cf.find(label_cf)
                rest = line[pos + len(label):].lstrip(" :：-–—")
                if rest:
                    return rest.strip()
                if i + 1 < len(lines):
                    nxt = lines[i + 1].strip()
                    # Avoid returning another obvious label line.
                    if not any(k.casefold() in nxt.casefold() for k in (
                        "name", "নাম", "father", "পিতা", "mother", "মাতা",
                        "date of birth", "জন্ম", "nid", "national id", "জাতীয় পরিচয়"
                    )):
                        return nxt
    return ""


def parse_bangladesh_nid_text(text: str) -> Dict[str, object]:
    """Extract conservative structured fields from Bangladesh NID OCR text.

    The parser does not fabricate fields. Ambiguous/missing values stay empty.
    """
    raw = text or ""
    normalized = _ascii_digits(raw)
    lines = _lines(normalized)

    name_bn = _label_value(lines, ("নাম",))
    name_en = _label_value(lines, ("Name", "Name (English)", "English Name"))
    father = _label_value(lines, ("পিতা", "Father", "Father's Name", "Father Name"))
    mother = _label_value(lines, ("মাতা", "Mother", "Mother's Name", "Mother Name"))
    dob = _label_value(lines, ("Date of Birth", "DOB", "জন্ম তারিখ", "জন্মতারিখ"))

    if dob:
        m = re.search(r"\b(\d{1,2})[\-/. ]([A-Za-z]{3,9}|\d{1,2})[\-/. ,]+(\d{4})\b", dob)
        if m:
            dob = m.group(0)
    if not dob:
        patterns = (
            r"\b\d{1,2}[\-/.]\d{1,2}[\-/.]\d{4}\b",
            r"\b\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}\b",
        )
        for p in patterns:
            m = re.search(p, normalized, re.I)
            if m:
                dob = m.group(0)
                break

    nid = ""
    # Bangladesh NID commonly appears as 10, 13 or 17 digits. OCR may insert spaces/hyphens.
    labeled = _label_value(lines, ("NID No", "NID Number", "National ID", "ID NO", "জাতীয় পরিচয় নং", "জাতীয় পরিচয় নং"))
    candidates = [labeled] + lines
    for candidate in candidates:
        compact = re.sub(r"[^0-9]", "", candidate)
        if len(compact) in (10, 13, 17):
            nid = compact
            if candidate == labeled:
                break
    if not nid:
        for m in re.finditer(r"(?<!\d)(?:\d[\s\-]*){10,17}(?!\d)", normalized):
            compact = re.sub(r"\D", "", m.group(0))
            if len(compact) in (10, 13, 17):
                nid = compact
                break

    blood = ""
    m = re.search(r"(?:Blood\s*Group|রক্তের\s*গ্রুপ)\s*[:：-]?\s*(A|B|AB|O)\s*([+-])", normalized, re.I)
    if m:
        blood = (m.group(1) + m.group(2)).upper()

    # Some older cards use "Name:" once for English only. Keep it in English field.
    if name_en and any("নাম" in x and name_bn == x for x in lines):
        name_bn = ""

    fields = {
        "name_bengali": name_bn,
        "name_english": name_en,
        "father_name": father,
        "mother_name": mother,
        "date_of_birth": dob,
        "nid_number": nid,
        "blood_group": blood,
    }
    found = sum(1 for v in fields.values() if v)
    return {
        **fields,
        "fields_found": found,
        "source_text": raw.strip(),
    }


def format_nid_result(data: Dict[str, object]) -> str:
    labels = [
        ("Name (Bangla)", "name_bengali"),
        ("Name (English)", "name_english"),
        ("Father", "father_name"),
        ("Mother", "mother_name"),
        ("Date of Birth", "date_of_birth"),
        ("NID Number", "nid_number"),
        ("Blood Group", "blood_group"),
    ]
    rows = [f"{label}: {data.get(key) or 'Not found'}" for label, key in labels]
    rows.append(f"Fields detected: {int(data.get('fields_found') or 0)}/{len(labels)}")
    rows.append("\nOCR TEXT\n--------------------\n" + str(data.get("source_text") or ""))
    return "\n".join(rows)


# ICAO Doc 9303 MRZ checksum weights.
_MRZ_WEIGHTS = (7, 3, 1)
_MRZ_VALUES = {"<": 0}
_MRZ_VALUES.update({str(i): i for i in range(10)})
_MRZ_VALUES.update({chr(ord("A") + i): 10 + i for i in range(26)})


def mrz_check_digit(field: str) -> str:
    total = 0
    for i, ch in enumerate((field or "").upper()):
        total += _MRZ_VALUES.get(ch, 0) * _MRZ_WEIGHTS[i % 3]
    return str(total % 10)


def _mrz_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("<", " ")).strip()


def _mrz_date(value: str, kind: str) -> str:
    if not re.fullmatch(r"\d{6}", value or ""):
        return value or ""
    yy, mm, dd = int(value[:2]), int(value[2:4]), int(value[4:6])
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return value
    now_yy = datetime.now(timezone.utc).year % 100
    if kind == "birth":
        year = 1900 + yy if yy > now_yy else 2000 + yy
        # A 5-year-old threshold prevents future-ish OCR values becoming 2000s incorrectly.
        if year > datetime.now(timezone.utc).year:
            year -= 100
    else:
        # Passport expiry is normally current/future; 00-79 -> 2000s, 80-99 -> 1900s.
        year = 2000 + yy if yy < 80 else 1900 + yy
    try:
        return datetime(year, mm, dd).strftime("%Y-%m-%d")
    except ValueError:
        return value


def normalize_td3_mrz(text: str) -> Optional[Tuple[str, str]]:
    """Find/normalize two 44-character TD3 passport MRZ lines from OCR text."""
    raw_lines = []
    for line in _lines(text.upper()):
        line = re.sub(r"[^A-Z0-9<]", "", line)
        if len(line) >= 35:
            raw_lines.append(line)
    for i in range(len(raw_lines) - 1):
        a, b = raw_lines[i], raw_lines[i + 1]
        if a.startswith("P"):
            if len(a) >= 44 and len(b) >= 44:
                return a[:44], b[:44]
    return None


def parse_passport_mrz(text: str) -> Dict[str, object]:
    pair = normalize_td3_mrz(text)
    if not pair:
        return {"valid_mrz": False, "error": "No 2-line TD3 passport MRZ (44 characters per line) was detected."}

    line1, line2 = pair
    document_type = line1[0:2].replace("<", "")
    issuer = line1[2:5].replace("<", "")
    name_block = line1[5:44]
    name_parts = name_block.split("<<", 1)
    surname = _mrz_name(name_parts[0])
    given_names = _mrz_name(name_parts[1] if len(name_parts) > 1 else "")

    passport_number = line2[0:9].replace("<", "")
    passport_cd = line2[9]
    nationality = line2[10:13].replace("<", "")
    birth_raw = line2[13:19]
    birth_cd = line2[19]
    sex = line2[20].replace("<", "X")
    expiry_raw = line2[21:27]
    expiry_cd = line2[27]
    personal = line2[28:42]
    personal_cd = line2[42]
    final_cd = line2[43]

    checks = {
        "passport_number": mrz_check_digit(line2[0:9]) == passport_cd,
        "date_of_birth": mrz_check_digit(birth_raw) == birth_cd,
        "expiry_date": mrz_check_digit(expiry_raw) == expiry_cd,
        "personal_number": mrz_check_digit(personal) == personal_cd,
        "composite": mrz_check_digit(line2[0:10] + line2[13:20] + line2[21:43]) == final_cd,
    }

    return {
        "valid_mrz": all(checks.values()),
        "document_type": document_type,
        "issuing_country": issuer,
        "surname": surname,
        "given_names": given_names,
        "passport_number": passport_number,
        "nationality": nationality,
        "date_of_birth": _mrz_date(birth_raw, "birth"),
        "sex": sex,
        "expiry_date": _mrz_date(expiry_raw, "expiry"),
        "personal_number": personal.replace("<", "").strip(),
        "checks": checks,
        "line1": line1,
        "line2": line2,
    }


def format_mrz_result(data: Dict[str, object]) -> str:
    if data.get("error"):
        return str(data["error"])
    checks = data.get("checks") or {}
    rows = [
        f"MRZ overall: {'VALID' if data.get('valid_mrz') else 'CHECK FAILED'}",
        f"Document type: {data.get('document_type') or 'Not found'}",
        f"Issuing country: {data.get('issuing_country') or 'Not found'}",
        f"Surname: {data.get('surname') or 'Not found'}",
        f"Given names: {data.get('given_names') or 'Not found'}",
        f"Passport number: {data.get('passport_number') or 'Not found'}",
        f"Nationality: {data.get('nationality') or 'Not found'}",
        f"Date of birth: {data.get('date_of_birth') or 'Not found'}",
        f"Sex: {data.get('sex') or 'Not found'}",
        f"Expiry date: {data.get('expiry_date') or 'Not found'}",
        f"Personal number: {data.get('personal_number') or 'Not found'}",
        "\nCHECK DIGITS",
    ]
    for key in ("passport_number", "date_of_birth", "expiry_date", "personal_number", "composite"):
        rows.append(f"{key.replace('_', ' ').title()}: {'PASS' if checks.get(key) else 'FAIL'}")
    rows += ["\nMRZ", str(data.get("line1") or ""), str(data.get("line2") or "")]
    return "\n".join(rows)
