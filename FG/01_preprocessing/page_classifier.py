"""Page-level direct-text confidence scoring for smart PDF extraction."""

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
    """Estimate how much extracted text looks like PDF extraction noise."""
    if not text:
        return 1.0

    noisy_chars = len(_NOISE_CHAR_PATTERN.findall(text))
    noisy_chars += sum(len(match.group(0)) for match in _REPEATED_SYMBOL_PATTERN.finditer(text))
    noisy_chars += len(_ISOLATED_SINGLE_CHAR_PATTERN.findall(text))
    return min(noisy_chars / max(len(text), 1), 1.0)


def score_confidence(text: str) -> tuple[float, list[str]]:
    """Score whether direct PDF text is good enough to avoid OCR."""
    char_count = len(text)
    word_count = len(text.split())
    alphabetic_ratio = sum(c.isalpha() for c in text) / max(char_count, 1)
    noise_ratio = compute_noise_ratio(text)
    markers_found = [m for m in LEGAL_MARKERS if m.lower() in text.lower()]

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


def classify_page(page_num: int, direct_text: str, threshold: float) -> PageResult:
    """Classify one 1-indexed PDF page as direct-text or OCR-required."""
    confidence, markers = score_confidence(direct_text)
    char_count = len(direct_text)
    word_count = len(direct_text.split())

    if confidence >= threshold:
        page_type: Literal["digital_text", "hybrid"] = "digital_text" if confidence >= 0.85 else "hybrid"
        return PageResult(
            page_num=page_num,
            page_type=page_type,
            direct_text=direct_text,
            direct_text_confidence=confidence,
            needs_ocr=False,
            ocr_text="",
            final_text=direct_text,
            extraction_method="direct_text",
            legal_markers_found=markers,
            char_count=char_count,
            word_count=word_count,
            reason=f"direct_text_confidence={confidence:.2f} >= threshold={threshold}",
        )

    page_type = "low_confidence" if confidence > 0 else "scanned_image"
    return PageResult(
        page_num=page_num,
        page_type=page_type,
        direct_text=direct_text,
        direct_text_confidence=confidence,
        needs_ocr=True,
        ocr_text="",
        final_text="",
        extraction_method="ocr",
        legal_markers_found=markers,
        char_count=char_count,
        word_count=word_count,
        reason=f"direct_text_confidence={confidence:.2f} < threshold={threshold}; routing to OCR",
    )
