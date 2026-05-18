"""Post-processing for OCR text from Hindi/English government documents.

Fixes common OCR errors:
1. Hindi-Arabic numeral normalization (१→1, all to Arabic)
2. Common character substitutions (tilde→hyphen, etc.)
3. Critical field validation (dates, amounts, reference numbers)
4. Whitespace cleanup
"""

import re
import logging

logger = logging.getLogger(__name__)

# ---------- Hindi numeral mapping ----------
_HINDI_TO_ARABIC = str.maketrans("०१२३४५६७८९", "0123456789")


def normalize_numerals(text: str) -> str:
    """Convert all Hindi numerals (०-९) to Arabic (0-9)."""
    return text.translate(_HINDI_TO_ARABIC)


# ---------- Common OCR character fixes ----------
# Patterns: (compiled_regex, replacement, description)
_CHAR_FIXES = [
    # Tilde used instead of hyphen in phone/fax numbers
    (re.compile(r"(\d)~(\d)"), r"\1-\2", "tilde→hyphen in numbers"),
    # Space inserted in email addresses
    (re.compile(r"(\w)@(\w+)\s+(\w+)"), r"\1@\2.\3", "space in email→dot"),
    # "pro chips@nic in" → "pro-chips@nic.in"
    (re.compile(r"pro\s+chips@nic\s+in"), "pro-chips@nic.in", "CHIPS email fix"),
    # I (capital i) used instead of 1 in dates like I8
    (re.compile(r"\bI(\d)"), r"1\1", "I→1 in numbers"),
    # Common Hindi OCR: फान → फ़ोन (keep as-is, just note)
    # ड → ड़ before specific vowels — too risky to auto-fix
    # $ instead of 5 in reference numbers
    (re.compile(r"(\d)\$"), r"\g<1>5", "$ →5 in numbers"),
    (re.compile(r"\$(\d)"), r"5\1", "$→5 in numbers"),
    # HTML entities from Docling markdown (e.g. &amp; → &)
    (re.compile(r"&amp;"), "&", "HTML entity &amp;"),
    (re.compile(r"&lt;"), "<", "HTML entity &lt;"),
    (re.compile(r"&gt;"), ">", "HTML entity &gt;"),
    # Stray single characters that are OCR noise
    (re.compile(r"^\s*[A-Z]{1,3}\s*$", re.MULTILINE), "", "stray Latin chars"),
    # Multiple blank lines → single blank line
    (re.compile(r"\n{3,}"), "\n\n", "excess blank lines"),
    # Trailing whitespace
    (re.compile(r"[ \t]+$", re.MULTILINE), "", "trailing whitespace"),
]


def fix_common_ocr_errors(text: str) -> str:
    """Apply common OCR error corrections."""
    for pattern, replacement, _desc in _CHAR_FIXES:
        text = pattern.sub(replacement, text)
    return text


# ---------- Critical field extraction & validation ----------
# These patterns find dates, amounts, reference numbers for flagging

_DATE_PATTERN = re.compile(
    r"(?:दिनांक|दिनाक|दिनाँक)[\s:—-]*"
    r"(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{2,4})",
    re.UNICODE,
)

_AMOUNT_PATTERN = re.compile(
    r"(?:रु[\s.]*|₹\s*)([\d,.]+)\s*"
    r"(करोड़|करोड|करड़|करड|लाख|हजार)?",
    re.UNICODE,
)

_REF_NUMBER_PATTERN = re.compile(
    r"(?:क्रमांक|कमांक|क्रमाक|क्र\.\s*)\s*([\d/$\s]+)",
    re.UNICODE,
)


def extract_critical_fields(text: str) -> dict:
    """Extract dates, amounts, and reference numbers for validation.

    Returns a dict with lists of found values and any quality flags.
    """
    fields = {
        "dates": [],
        "amounts": [],
        "reference_numbers": [],
        "quality_flags": [],
    }

    # Dates
    for m in _DATE_PATTERN.finditer(text):
        day, month, year = m.group(1), m.group(2), m.group(3)
        date_str = f"{day}/{month}/{year}"
        fields["dates"].append({"raw": m.group(0), "parsed": date_str})
        # Flag suspicious dates
        if int(day) > 31 or int(month) > 12:
            fields["quality_flags"].append(
                f"Suspicious date: {date_str} (raw: {m.group(0)})"
            )

    # Amounts
    for m in _AMOUNT_PATTERN.finditer(text):
        amount_str = m.group(1).replace(",", "")
        unit = m.group(2) or ""
        fields["amounts"].append({
            "raw": m.group(0),
            "value": amount_str,
            "unit": unit,
        })

    # Reference numbers
    for m in _REF_NUMBER_PATTERN.finditer(text):
        ref = m.group(1).strip()
        fields["reference_numbers"].append({"raw": m.group(0), "ref": ref})
        # Flag if it contains $ (likely OCR error for 5)
        if "$" in ref:
            fields["quality_flags"].append(
                f"Reference number may have OCR error ($ for 5): {ref}"
            )

    return fields


def postprocess_page_text(text: str) -> str:
    """Full post-processing pipeline for a single page's text."""
    text = normalize_numerals(text)
    text = fix_common_ocr_errors(text)
    return text.strip()


def postprocess_document(pages_text: list[str]) -> tuple[list[str], dict]:
    """Post-process all pages and extract critical fields.

    Returns (processed_pages, document_fields) where document_fields
    aggregates all dates, amounts, references, and quality flags.
    """
    processed = []
    all_fields = {
        "dates": [],
        "amounts": [],
        "reference_numbers": [],
        "quality_flags": [],
    }

    for i, text in enumerate(pages_text):
        cleaned = postprocess_page_text(text)
        processed.append(cleaned)

        fields = extract_critical_fields(cleaned)
        for key in all_fields:
            for item in fields[key]:
                if isinstance(item, dict):
                    item["page"] = i + 1
                all_fields[key].append(item)

    # Document-level quality checks
    if not all_fields["dates"]:
        all_fields["quality_flags"].append("No dates found in entire document")
    if not all_fields["reference_numbers"]:
        all_fields["quality_flags"].append(
            "No reference numbers found in entire document"
        )

    if all_fields["quality_flags"]:
        logger.warning(
            f"Quality flags: {len(all_fields['quality_flags'])} issues found"
        )
        for flag in all_fields["quality_flags"]:
            logger.warning(f"  ⚠ {flag}")

    return processed, all_fields
