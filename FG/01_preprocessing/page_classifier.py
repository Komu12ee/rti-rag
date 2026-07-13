"""Page-level routing for smart PDF extraction.

Routing rule:
- If a PDF page contains one or more embedded/raster images, route it to OCR.
- If a PDF page contains no image, keep direct selectable text, regardless of
  character count, word count, or confidence score.

The confidence score is retained only as quality metadata. It does not decide
whether OCR runs.
"""

from __future__ import annotations

import re
from typing import Literal, TypedDict


class PageResult(TypedDict):
    page_num: int
    page_type: Literal["digital_text", "scanned_image", "hybrid", "low_confidence"]
    direct_text: str
    direct_text_confidence: float
    needs_ocr: bool
    ocr_text: str
    final_text: str
    extraction_method: Literal["direct_text", "ocr", "hybrid", "failed"]
    legal_markers_found: list[str]
    char_count: int
    word_count: int
    image_count: int
    reason: str


LEGAL_MARKERS = [
    "File No",
    "RTI application",
    "CPIO reply",
    "Facts",
    "Grounds for Second Appeal",
    "Order",
    "Appellant",
    "Respondent",
]

_NOISE_CHAR_PATTERN = re.compile(r"[^\x20-\x7E\u0900-\u097F\n\r\t]")
_REPEATED_SYMBOL_PATTERN = re.compile(r"([^\w\s])\1{2,}")
_ISOLATED_SINGLE_CHAR_PATTERN = re.compile(r"(?:^|\s)[A-Za-z](?=\s|$)")


def compute_noise_ratio(text: str) -> float:
    """Estimate how much directly extracted text looks like extraction noise."""
    if not text:
        return 1.0

    noisy_chars = len(_NOISE_CHAR_PATTERN.findall(text))
    noisy_chars += sum(
        len(match.group(0))
        for match in _REPEATED_SYMBOL_PATTERN.finditer(text)
    )
    noisy_chars += len(_ISOLATED_SINGLE_CHAR_PATTERN.findall(text))
    return min(noisy_chars / max(len(text), 1), 1.0)


def score_confidence(text: str) -> tuple[float, list[str]]:
    """Calculate direct-text quality metadata.

    This score is informational only. It does not route a page to OCR.
    """
    char_count = len(text)
    word_count = len(text.split())
    alphabetic_ratio = sum(c.isalpha() for c in text) / max(char_count, 1)
    noise_ratio = compute_noise_ratio(text)
    markers_found = [
        marker
        for marker in LEGAL_MARKERS
        if marker.lower() in text.lower()
    ]

    confidence = 0.0
    if char_count > 500:
        confidence += 0.25
    if word_count > 80:
        confidence += 0.20
    if len(markers_found) >= 2:
        confidence += 0.25
    if alphabetic_ratio > 0.60:
        confidence += 0.15
    if noise_ratio < 0.15:
        confidence += 0.15

    return round(min(confidence, 1.0), 4), markers_found


def classify_page(
    page_num: int,
    direct_text: str,
    image_count: int,
) -> PageResult:
    """Classify a page using image presence as the only automatic OCR trigger.

    Rules:
    1. image_count > 0 and direct text exists -> hybrid; OCR required.
    2. image_count > 0 and direct text is empty -> scanned image; OCR required.
    3. image_count == 0 -> direct text; OCR not required, even when text is
       short or empty.
    """
    confidence, markers = score_confidence(direct_text)
    char_count = len(direct_text)
    word_count = len(direct_text.split())
    has_direct_text = bool(direct_text.strip())

    if image_count > 0:
        if has_direct_text:
            page_type: Literal["hybrid", "scanned_image"] = "hybrid"
            extraction_method: Literal["hybrid", "ocr"] = "hybrid"
            reason = (
                f"detected {image_count} image(s); "
                "page has direct text, so routing to OCR as hybrid"
            )
        else:
            page_type = "scanned_image"
            extraction_method = "ocr"
            reason = (
                f"detected {image_count} image(s); "
                "no direct text found, so routing to OCR"
            )

        return PageResult(
            page_num=page_num,
            page_type=page_type,
            direct_text=direct_text,
            direct_text_confidence=confidence,
            needs_ocr=True,
            ocr_text="",
            final_text="",
            extraction_method=extraction_method,
            legal_markers_found=markers,
            char_count=char_count,
            word_count=word_count,
            image_count=image_count,
            reason=reason,
        )

    # No image means no OCR, regardless of text length or confidence.
    page_type_no_image: Literal["digital_text", "low_confidence"] = (
        "digital_text" if has_direct_text else "low_confidence"
    )
    return PageResult(
        page_num=page_num,
        page_type=page_type_no_image,
        direct_text=direct_text,
        direct_text_confidence=confidence,
        needs_ocr=False,
        ocr_text="",
        final_text=direct_text,
        extraction_method="direct_text",
        legal_markers_found=markers,
        char_count=char_count,
        word_count=word_count,
        image_count=0,
        reason=(
            "no image detected; using direct text without considering "
            "text length or confidence"
        ),
    )