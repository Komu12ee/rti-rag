import re
import unicodedata

from services.retrieval_plan import Route, RouterDecision


EMAIL_PATTERN = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
OFFICE_CODE_PATTERN = re.compile(r"(?<!\d)\d{10}(?!\d)")

# Directory roles. Keep the aliases aligned with officer_query_parser.py.
POSTGRES_ROLE_TERMS = (
    "pio",
    "faa",
    "public information officer",
    "first appellate officer",
    "first appellate authority",
    "public information authority",
    "जन सूचना अधिकारी",
    "लोक सूचना अधिकारी",
    "प्रथम अपीलीय अधिकारी",
    "प्रथम अपीलीय प्राधिकारी",
)

POSTGRES_LOOKUP_TERMS = (
    "who is",
    "find",
    "show",
    "list",
    "contact",
    "email",
    "address",
    "phone",
    "mobile",
    "count",
    "name",
    "ऑफिसर का नाम",
    "कौन है",
    "कौन हैं",
    "दिखाओ",
    "दिखाइए",
    "सूची",
    "ईमेल",
    "पता",
    "फोन",
    "मोबाइल",
    "नाम",
    "कितने",
)

POSTGRES_ENTITY_TERMS = (
    "office",
    "school",
    "department",
    "district",
    "college",
    "hospital",
    "panchayat",
    "collector",
    "tehsil",
    "police station",
    "कार्यालय",
    "विद्यालय",
    "स्कूल",
    "विभाग",
    "जिला",
    "पंचायत",
    "कलेक्टर",
    "तहसील",
    "थाना",
)

LEGAL_TERMS = (
    "rti act",
    "section",
    "appeal",
    "first appeal",
    "second appeal",
    "exemption",
    "payment",
    "payments",
    "payment option",
    "payment options",
    "online payment",
    "fee",
    "fees",
    "rti fee",
    "application fee",
    "bpl",
    "payment gateway",
    "penalty",
    "precedent",
    "cic",
    "sic",
    "decision",
    "circular",
    "rule",
    "procedure",
    "time limit",
    "reply time",
    "record retention",
    "legal position",
    "धारा",
    "अपील",
    "प्रथम अपील",
    "द्वितीय अपील",
    "छूट",
    "दंड",
    "निर्णय",
    "परिपत्र",
    "नियम",
    "प्रक्रिया",
    "समय सीमा",
    "कितने दिन",
    "रिकॉर्ड संरक्षण",
    "अभिलेख",
    "does not reply",
    "no reply",
    "no response",
    "failure to reply",
    "what can applicant do",
    "what can an applicant do",
    "next step",
    "reply not received",
    "जवाब नहीं मिला",
    "उत्तर नहीं मिला",
    "जवाब नहीं दिया",
    "उत्तर नहीं दिया",
    "जवाब नहीं दे",
    "उत्तर नहीं दे",
    "जवाब नहीं देता",
    "उत्तर नहीं देता",
    "क्या किया जा सकता है",
    "क्या कर सकते हैं",
    "कानूनी रूप से",
    "आगे क्या करें",
    "क्या कर सकता है",
)

LEGAL_EXPLANATION_TERMS = (
    "what is",
    "meaning",
    "meaning of",
    "duties",
    "duty",
    "responsibility",
    "what should",
    "how to file",
    "कैसे",
    "क्या है",
    "मतलब",
    "कर्तव्य",
    "जिम्मेदारी",
    "काम क्या है",
)


def normalize_query(query: str) -> str:
    text = unicodedata.normalize("NFKC", query or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip().casefold()


def contains_any(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term in text]


def route_query(query: str) -> RouterDecision:
    """
    Router A: deterministic and free.

    Important directory rule:
    A query mentioning PIO/FAA is a registry lookup by default. It must not
    fall into the generic UNCLEAR -> legal-Qdrant path merely because the user
    wrote a concise query such as "PIO of Balrampur".

    Legal questions remain legal Qdrant when they ask about a section, duty,
    procedure, time limit, appeal, exemption, etc., without requesting a
    specific officer / office / district / department.
    """
    normalized = normalize_query(query)

    if not normalized:
        return RouterDecision(
            route=Route.UNCLEAR,
            confidence=0.0,
            reason="Query is empty.",
            matched_signals=(),
        )

    signals: list[str] = []
    postgres_score = 0
    legal_score = 0

    has_email = bool(EMAIL_PATTERN.search(normalized))
    has_office_code = bool(OFFICE_CODE_PATTERN.search(normalized))

    role_hits = contains_any(normalized, POSTGRES_ROLE_TERMS)
    lookup_hits = contains_any(normalized, POSTGRES_LOOKUP_TERMS)
    entity_hits = contains_any(normalized, POSTGRES_ENTITY_TERMS)
    legal_hits = contains_any(normalized, LEGAL_TERMS)
    explanation_hits = contains_any(normalized, LEGAL_EXPLANATION_TERMS)

    if has_email:
        postgres_score += 5
        signals.append("email")

    if has_office_code:
        postgres_score += 5
        signals.append("office_code")

    if role_hits:
        postgres_score += 1
        signals.extend(f"role:{item}" for item in role_hits)

    if role_hits and lookup_hits:
        postgres_score += 4
        signals.extend(f"lookup:{item}" for item in lookup_hits)

    if role_hits and entity_hits:
        postgres_score += 2
        signals.extend(f"entity:{item}" for item in entity_hits)

    if legal_hits:
        legal_score += min(len(legal_hits) * 2, 6)
        signals.extend(f"legal:{item}" for item in legal_hits)

    if explanation_hits and not has_email and not has_office_code:
        legal_score += 2
        signals.extend(f"explanation:{item}" for item in explanation_hits)

    # "What are PIO duties under Section 5?" is legal.
    # "PIO of Balod", "FAA of Balod district", and Hindi equivalents are
    # officer-directory lookups even without words such as "find" or "show".
    legal_only_role_question = bool(
        role_hits
        and legal_score >= 2
        and not lookup_hits
        and not entity_hits
        and not has_email
        and not has_office_code
    )

    # A directory query with legal and registry signals needs both sources.
    if (
        postgres_score >= 3
        and legal_score >= 2
        and not legal_only_role_question
    ):
        return RouterDecision(
            route=Route.HYBRID,
            confidence=0.92,
            reason="Detected officer-directory lookup and RTI legal/procedural intent.",
            matched_signals=tuple(signals),
        )

    if legal_only_role_question or (
        legal_score >= 2 and postgres_score < 3
    ):
        return RouterDecision(
            route=Route.QDRANT,
            confidence=0.88,
            reason="Detected an RTI legal, procedural, or precedent query.",
            matched_signals=tuple(signals),
        )

    # The critical fix: role alone is enough to enter the officer lookup path.
    if role_hits:
        return RouterDecision(
            route=Route.POSTGRES,
            confidence=0.88,
            reason="Detected a PIO/FAA officer-directory lookup.",
            matched_signals=tuple(signals),
        )

    if postgres_score >= 4:
        return RouterDecision(
            route=Route.POSTGRES,
            confidence=0.90,
            reason="Detected a structured officer/office registry lookup.",
            matched_signals=tuple(signals),
        )

    if legal_score >= 2:
        return RouterDecision(
            route=Route.QDRANT,
            confidence=0.88,
            reason="Detected an RTI legal, procedural, or precedent query.",
            matched_signals=tuple(signals),
        )

    return RouterDecision(
        route=Route.UNCLEAR,
        confidence=0.35,
        reason="No reliable structured-data or legal-document intent was detected.",
        matched_signals=tuple(signals),
    )
