from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit, urlunsplit


_ALLOWED_FIELDS = frozenset(
    {
        "adapter_id",
        "byte_count",
        "cache_hit",
        "cache_status",
        "candidate_count",
        "chatbot_team",
        "domain",
        "elapsed_ms",
        "error_code",
        "extraction_method",
        "final_status",
        "http_status",
        "ocr_used",
        "result_status",
        "results_examined",
        "source_type",
        "status",
        "trigger_reason",
        "trigger_source",
        "triggered",
        "verified_item_count",
    }
)
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "body",
    "cookie",
    "credential",
    "password",
    "query",
    "raw",
    "secret",
    "token",
)


def query_sha256(query: str) -> str:
    return hashlib.sha256(str(query or "").encode("utf-8")).hexdigest()


def _safe_identifier(value: Any, *, maximum: int = 160) -> str:
    return str(value or "").strip()[:maximum]


def _safe_url(value: Any) -> str | None:
    try:
        parsed = urlsplit(str(value or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        hostname = parsed.hostname.casefold().rstrip(".")
        try:
            port = parsed.port
        except ValueError:
            return None
        netloc = hostname if port is None else f"{hostname}:{port}"
        # Query strings, fragments, and user-info can carry credentials or RTI data.
        return urlunsplit((parsed.scheme, netloc, parsed.path or "/", "", ""))
    except (TypeError, ValueError):
        return None


def _safe_scalar(value: Any) -> str | int | float | bool | None:
    if isinstance(value, Enum):
        value = value.value
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)[:1000]


def _safe_sequence(value: Any) -> list[str | int | float | bool | None]:
    items = list(value) if isinstance(value, (list, tuple, set, frozenset)) else [value]
    return [_safe_scalar(item) for item in items[:50]]


def _safe_sources(value: Any) -> list[str]:
    items = list(value) if isinstance(value, (list, tuple, set, frozenset)) else [value]
    sources: list[str] = []
    for item in items[:50]:
        candidate = item.get("domain") if isinstance(item, Mapping) else item
        text = _safe_identifier(candidate, maximum=253).casefold().rstrip(".")
        if text and all(character not in text for character in "/\\@?#"):
            sources.append(text)
    return sources


class Section4AuditLogger:
    """Emit bounded JSON audit events without raw requests or retrieved bodies."""

    def __init__(
        self,
        logger: logging.Logger | Any | None = None,
        *,
        now: Callable[[], datetime] | None = None,
        chatbot_team: str | None = None,
    ) -> None:
        self.logger = logger or logging.getLogger("section4_web_verification.audit")
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.chatbot_team = _safe_identifier(chatbot_team, maximum=160)

    def emit(
        self,
        event: str,
        *,
        request_id: str,
        verification_id: str | None = None,
        query: str | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        safe_request_id = _safe_identifier(request_id)
        if not safe_request_id:
            raise ValueError("request_id is required for Section 4 audit events")

        timestamp = self._now()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        payload: dict[str, Any] = {
            "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
            "event": _safe_identifier(event, maximum=120),
            "request_id": safe_request_id,
        }
        if self.chatbot_team:
            payload["chatbot_team"] = self.chatbot_team

        safe_verification_id = _safe_identifier(verification_id)
        if safe_verification_id:
            payload["verification_id"] = safe_verification_id
        if query is not None:
            payload["query_sha256"] = query_sha256(query)

        requested_url = _safe_url(fields.get("requested_url"))
        if requested_url:
            payload["requested_url"] = requested_url
        requested_urls = [
            safe
            for safe in (_safe_url(value) for value in fields.get("requested_urls", ()))
            if safe
        ]
        if requested_urls:
            payload["requested_urls"] = requested_urls[:50]

        selected_sources = _safe_sources(fields.get("selected_sources", ()))
        if selected_sources:
            payload["selected_sources"] = selected_sources

        search_terms = fields.get("generated_search_terms", fields.get("search_terms", ()))
        if isinstance(search_terms, str):
            search_terms = [search_terms]
        if isinstance(search_terms, (list, tuple, set, frozenset)):
            hashes = [query_sha256(str(term)) for term in list(search_terms)[:50] if str(term)]
            if hashes:
                payload["search_term_sha256"] = hashes

        for key in _ALLOWED_FIELDS:
            if key not in fields:
                continue
            lowered = key.casefold()
            if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
                continue
            value = fields[key]
            if isinstance(value, (list, tuple, set, frozenset)):
                payload[key] = _safe_sequence(value)
            else:
                payload[key] = _safe_scalar(value)

        self.logger.info(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
        return payload
