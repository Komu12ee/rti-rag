from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


EMAIL_PATTERN = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)

OFFICE_CODE_PATTERN = re.compile(r"(?<!\d)\d{10}(?!\d)")

OFFICER_HINTS = (
    "pio",
    "faa",
    "public information officer",
    "first appellate officer",
    "first appellate authority",
    "जन सूचना अधिकारी",
    "लोक सूचना अधिकारी",
    "प्रथम अपीलीय अधिकारी",
    "officer record",
    "officer details",
    "email",
    "ईमेल",
    "कार्यालय",
    "office",
    "district",
    "जिला",
    "department",
    "विभाग",
)

LEGAL_HINTS = (
    "rti act",
    "act",
    "section",
    "धारा",
    "appeal",
    "first appeal",
    "second appeal",
    "time limit",
    "timeline",
    "reply",
    "response",
    "उत्तर",
    "जवाब",
    "penalty",
    "fine",
    "exemption",
    "procedure",
    "process",
    "कानूनी",
    "क्या करना",
    "क्या कर सकते",
)


@dataclass(frozen=True)
class HybridQueryParts:
    original_query: str
    registry_query: str
    legal_query: str
    registry_clauses: tuple[str, ...]
    legal_clauses: tuple[str, ...]


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _contains_hint(text: str, hint: str) -> bool:
    text_lower = text.casefold()
    hint_lower = hint.casefold()

    # Avoid matching short English words inside other words.
    if re.fullmatch(r"[A-Za-z0-9 ]+", hint):
        pattern = rf"(?<![A-Za-z0-9]){re.escape(hint_lower)}(?![A-Za-z0-9])"
        return bool(re.search(pattern, text_lower))

    return hint_lower in text_lower


def _officer_score(clause: str) -> int:
    score = 0

    if EMAIL_PATTERN.search(clause):
        score += 5

    if OFFICE_CODE_PATTERN.search(clause):
        score += 5

    for hint in OFFICER_HINTS:
        if _contains_hint(clause, hint):
            score += 2

    return score


def _legal_score(clause: str) -> int:
    score = 0

    for hint in LEGAL_HINTS:
        if _contains_hint(clause, hint):
            score += 2

    return score


def split_hybrid_query(query: str) -> HybridQueryParts:
    """
    Split a mixed officer + legal question deterministically.

    Example:
    'बलरामपुर के PIO का नाम और RTI reply की time limit बताओ'

    Registry query:
    'बलरामपुर के PIO का नाम'

    Legal query:
    'RTI reply की time limit बताओ'
    """
    normalized = _normalize_text(query)

    clauses = [
        part.strip()
        for part in re.split(r"\s*(?:\band\b|और|;|\n)\s*", normalized, flags=re.IGNORECASE)
        if part.strip()
    ]

    registry_clauses: list[str] = []
    legal_clauses: list[str] = []

    for clause in clauses:
        officer_score = _officer_score(clause)
        legal_score = _legal_score(clause)

        if officer_score > legal_score and officer_score > 0:
            registry_clauses.append(clause)
        elif legal_score > 0:
            legal_clauses.append(clause)

    # Safe fallback: do not discard the full query if split was inconclusive.
    registry_query = " ".join(registry_clauses).strip() or normalized
    legal_query = " ".join(legal_clauses).strip() or normalized

    return HybridQueryParts(
        original_query=normalized,
        registry_query=registry_query,
        legal_query=legal_query,
        registry_clauses=tuple(registry_clauses),
        legal_clauses=tuple(legal_clauses),
    )