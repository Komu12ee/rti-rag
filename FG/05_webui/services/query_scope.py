from __future__ import annotations

import re
import unicodedata


CURRENT_QUESTION_MARKER = re.compile(
    r"(?im)^\s*(?:current\s+user\s+question|current\s+question)\s*:\s*"
)

SCOPED_QUERY_BOUNDARY = re.compile(
    r"(?im)^\s*(?:"
    r"recent\s+conversation\s+context|"
    r"assistant\s+role\s+and\s+answer\s+scope"
    r")\s*:\s*"
)

def normalize_query_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return value.strip()


def extract_current_user_question(request_query: str) -> str:
    """
    Extract only the latest question from the frontend scoped payload.

    Frontend format:
        Current user question: ...
        Recent conversation context: ...
        Assistant role and answer scope: ...
    """
    normalized = normalize_query_text(request_query)

    if not normalized:
        return ""

    markers = list(CURRENT_QUESTION_MARKER.finditer(normalized))

    # Normal direct question.
    if not markers:
        return normalized

    # Take text after the last current-question marker.
    remaining = normalized[markers[-1].end():]

    # Stop before frontend-added history/scope sections.
    boundary = SCOPED_QUERY_BOUNDARY.search(remaining)

    if boundary:
        current_question = remaining[:boundary.start()].strip()
    else:
        current_question = remaining.strip()

    current_question = re.sub(
        r"^```(?:text|markdown)?\s*|\s*```$",
        "",
        current_question,
        flags=re.IGNORECASE,
    ).strip()

    return current_question or normalized