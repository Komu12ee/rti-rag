from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from services.postgres_db import get_connection


EMAIL_PATTERN = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)

OFFICE_CODE_PATTERN = re.compile(r"(?<!\d)\d{10}(?!\d)")


ROLE_ALIASES = {
    "PIO": (
        "pio",
        "public information officer",
        "जन सूचना अधिकारी",
        "लोक सूचना अधिकारी",
    ),
    "FAA": (
        "faa",
        "first appellate officer",
        "प्रथम अपीलीय अधिकारी",
    ),
}
DISTRICT_ALIASES = {
    "BALRAMPUR": (
        "balrampur",
        "बलरामपुर",
        "बलरामपुर रामानुजगंज",
        "बलरामपुर-रामानुजगंज",
    ),
}

REMOVABLE_QUERY_TERMS = (
    "who is",
    "find",
    "show",
    "list",
    "give",
    "tell me",
    "contact",
    "email",
    "address",
    "officer",
    "office",
    "department",
    "district",
    "school",
    "college",
    "hospital",
    "pio",
    "faa",
    "public information officer",
    "first appellate officer",
    "का",
    "की",
    "के",
    "को",
    "में",
    "का नाम",
    "कौन है",
    "कौन हैं",
    "बताओ",
    "बताइए",
    "दिखाओ",
    "दिखाइए",
    "सूची",
    "नाम",
    "ईमेल",
    "पता",
    "कार्यालय",
    "विद्यालय",
    "स्कूल",
    "विभाग",
    "जिला",
    "the",
    "for",
    "in",
    "using",
    "with",
    "of",
    "please",
    "details",
    "this",
    "is",
    "are",
    "a",
    "an",
    "जिले के",
    "जिले",
    "kaun hai",
    "kaun",
    "hai",
    "ka",
    "ki",
    "ke",
    "mein",
    "me",
)


@dataclass(frozen=True)
class OfficerSearchCriteria:
    email: Optional[str] = None
    office_code: Optional[str] = None
    rti_role: Optional[str] = None
    district: Optional[str] = None
    department: Optional[str] = None
    search_text: Optional[str] = None

    def is_empty(self) -> bool:
        return not any(
            [
                self.email,
                self.office_code,
                self.rti_role,
                self.district,
                self.department,
                self.search_text,
            ]
        )


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _contains_phrase(query_lower: str, phrase: str) -> bool:
    return phrase.casefold() in query_lower


def _detect_role(query: str) -> Optional[str]:
    query_lower = query.casefold()

    for role, aliases in ROLE_ALIASES.items():
        if any(_contains_phrase(query_lower, alias) for alias in aliases):
            return role

    return None


def _load_districts() -> list[tuple[str, str]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT district_name, district_key
                FROM districts
                ORDER BY LENGTH(district_name) DESC;
                """
            )
            return [
                (row["district_name"], row["district_key"])
                for row in cur.fetchall()
            ]


def _load_departments() -> list[str]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT department_name
                FROM departments
                ORDER BY LENGTH(department_name) DESC;
                """
            )
            return [
                row["department_name"]
                for row in cur.fetchall()
            ]


def _detect_district(query: str) -> Optional[str]:
    query_lower = query.casefold()

    for district_name, district_key in _load_districts():
        possible_terms = [
            district_name,
            district_key,
            *_district_search_terms(district_name),
        ]

        for term in possible_terms:
            if term and term.casefold() in query_lower:
                return district_name

    return None
def _district_search_terms(district_name: str) -> tuple[str, ...]:
    return (
        district_name,
        *DISTRICT_ALIASES.get(district_name.upper(), ()),
    )

def _detect_department(query: str) -> Optional[str]:
    query_lower = query.casefold()

    for department_name in _load_departments():
        if department_name.casefold() in query_lower:
            return department_name

    return None

def _remove_phrase(text: str, phrase: str) -> str:
    """
    Remove an English phrase only when it is a full word/phrase.
    This prevents removing 'a' from 'totally' or 'in' from another word.
    Hindi phrases are removed as exact Unicode text.
    """
    phrase = normalize_text(phrase)

    if not phrase:
        return text

    if re.fullmatch(r"[A-Za-z0-9 ]+", phrase):
        pattern = rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])"
    else:
        pattern = re.escape(phrase)

    return re.sub(pattern, " ", text, flags=re.IGNORECASE)


def _remove_detected_parts(
    query: str,
    role: Optional[str],
    district: Optional[str],
    department: Optional[str],
    email: Optional[str],
    office_code: Optional[str],
) -> str:
    remaining = query

    values_to_remove = []

    if role:
        values_to_remove.extend(ROLE_ALIASES[role])

    if district:
        values_to_remove.extend(_district_search_terms(district))

    if department:
        values_to_remove.append(department)

    if email:
        values_to_remove.append(email)

    if office_code:
        values_to_remove.append(office_code)

    values_to_remove.extend(REMOVABLE_QUERY_TERMS)

    # Remove longer phrases first, so "public information officer"
    # is removed before "officer".
    for value in sorted(values_to_remove, key=len, reverse=True):
        if not value:
            continue
        remaining = _remove_phrase(remaining, value)

    remaining = re.sub(r"[?!.:,;()\-_/]+", " ", remaining)
    remaining = re.sub(r"\s+", " ", remaining).strip()

    # Very short leftover text is usually not a useful office search phrase.
    if len(remaining) < 2:
        return ""

    return remaining


def parse_officer_query(query: str) -> OfficerSearchCriteria:
    """
    Convert a natural-language officer query into safe structured criteria.

    This function never writes SQL and never calls an LLM.
    """
    normalized = normalize_text(query)

    email_match = EMAIL_PATTERN.search(normalized)
    office_code_match = OFFICE_CODE_PATTERN.search(normalized)

    email = email_match.group(0).lower() if email_match else None
    office_code = office_code_match.group(0) if office_code_match else None

    role = _detect_role(normalized)
    district = _detect_district(normalized)
    department = _detect_department(normalized)

    search_text = _remove_detected_parts(
        query=normalized,
        role=role,
        district=district,
        department=department,
        email=email,
        office_code=office_code,
    )

    return OfficerSearchCriteria(
        email=email,
        office_code=office_code,
        rti_role=role,
        district=district,
        department=department,
        search_text=search_text or None,
    )