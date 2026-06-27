from __future__ import annotations

import re
import unicodedata


CURRENT_QUESTION_MARKER = re.compile(
    r"(?im)^\s*(?:current\s+user\s+question|current\s+question)\s*:\s*"
)


def normalize_query_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return value.strip()


def extract_current_user_question(request_query: str) -> str:
    """
    Return the latest user question from a frontend scoped-query payload.

    If the frontend sends a direct normal question, return it unchanged.

    Scoped payload example:
        Previous conversation:
        User: What is Section 8?
        Assistant: ...

        Current user question:
        पकराड़ी स्कूल का PIO कौन है?
    """
    normalized = normalize_query_text(request_query)

    if not normalized:
        return ""

    markers = list(CURRENT_QUESTION_MARKER.finditer(normalized))

    # Normal direct question: do not alter it.
    if not markers:
        return normalized

    # Use the final marker to avoid routing based on old chat context.
    current_question = normalized[markers[-1].end():].strip()

    # Remove simple enclosing markdown fences if the frontend used them.
    current_question = re.sub(
        r"^```(?:text|markdown)?\s*|\s*```$",
        "",
        current_question,
        flags=re.IGNORECASE,
    ).strip()

    return current_question or normalized