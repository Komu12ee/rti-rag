from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate


DEVANAGARI_PATTERN = re.compile(r"[\u0900-\u097F]")

IAST_TO_ASCII = str.maketrans(
    {
        "ā": "a",
        "ī": "i",
        "ū": "u",
        "ṛ": "ri",
        "ṝ": "ri",
        "ḷ": "l",
        "ḹ": "l",
        "ṅ": "n",
        "ñ": "n",
        "ṭ": "t",
        "ḍ": "d",
        "ṇ": "n",
        "ś": "sh",
        "ṣ": "sh",
        "ṃ": "m",
        "ṁ": "m",
        "ḥ": "h",
    }
)
CANONICAL_NAME_TOKEN_ALIASES = {
    # Indic transliteration of सिंह commonly becomes simha/simh.
    # Citizens normally write Singh in English.
    "simha": "singh",
    "simh": "singh",
}

@dataclass(frozen=True)
class OfficerNameKeys:
    latin: str
    normalized: str
    search_key: str


def _remove_terminal_schwa(text: str) -> str:
    """
    Indic transliteration produces forms such as:
    rājeśa kumāra rāṭhaura

    For practical Indian-name search:
    rajesha kumara rathaura
    becomes:
    rajesh kumar rathaur
    """
    tokens: list[str] = []

    for token in text.split():
        if len(token) > 3 and token.endswith("a"):
            token = token[:-1]
        tokens.append(token)

    return " ".join(tokens)

def _canonicalize_name_tokens(text: str) -> str:
    tokens = []

    for token in text.split():
        tokens.append(
            CANONICAL_NAME_TOKEN_ALIASES.get(token, token)
        )

    return " ".join(tokens)


def _latinize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip()

    if not text:
        return ""

    if DEVANAGARI_PATTERN.search(text):
        text = transliterate(
            text,
            sanscript.DEVANAGARI,
            sanscript.IAST,
        )

    text = text.translate(IAST_TO_ASCII)

    # Remove any remaining accents safely.
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    text = text.casefold()
    text = text.replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    text = _remove_terminal_schwa(text)
    return _canonicalize_name_tokens(text)

def _build_search_key(latin: str) -> str:
    """
    Loose identity key.

    rathaur → rthr
    rathor  → rthr
    rathore → rthr

    This makes common Indian spelling variations searchable.
    """
    compact = re.sub(r"[^a-z]", "", latin.casefold())
    return re.sub(r"[aeiou]", "", compact)


def build_name_keys(value: str | None) -> OfficerNameKeys:
    latin = _latinize(str(value or ""))

    normalized = re.sub(
        r"[^a-z0-9]",
        "",
        latin,
    )

    return OfficerNameKeys(
        latin=latin,
        normalized=normalized,
        search_key=_build_search_key(latin),
    )