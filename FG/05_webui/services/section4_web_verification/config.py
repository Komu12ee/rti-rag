from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


# Reviewed defaults. Operators may add exact `.gov.in`/`.nic.in` department
# hosts through configuration; query text and model output can never add hosts.
BUILTIN_APPROVED_DOMAINS = frozenset(
    {
        "www.sci.gov.in",
        "sci.gov.in",
        "api.sci.gov.in",
        "www.cic.gov.in",
        "cic.gov.in",
        "www.siccg.gov.in",
        "siccg.gov.in",
        "rtionline.cg.gov.in",
        "www.rtionline.cg.gov.in",
        "cgeproc.cgstate.gov.in",
        "eproc.cgstate.gov.in",
        "gem.gov.in",
        "www.gem.gov.in",
        "bidplus.gem.gov.in",
        "eprocure.gov.in",
        "www.eprocure.gov.in",
    }
)


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


def _as_float(
    value: str | None,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


def _configured_official_domains(value: str | None) -> frozenset[str]:
    """Accept only exact operator-configured Indian government hostnames."""
    if not value:
        return frozenset()
    approved: set[str] = set()
    for item in value.split(","):
        domain = item.strip().casefold().rstrip(".")
        if (
            domain
            and "*" not in domain
            and ":" not in domain
            and "/" not in domain
            and "@" not in domain
            and (domain.endswith(".gov.in") or domain.endswith(".nic.in"))
        ):
            approved.add(domain)
    return frozenset(approved)


def _approved_domains(value: str | None, department_value: str | None) -> frozenset[str]:
    department_domains = _configured_official_domains(department_value)
    if value is None:
        return BUILTIN_APPROVED_DOMAINS | department_domains
    requested = _configured_official_domains(value)
    return frozenset(requested | department_domains)


@dataclass(frozen=True)
class Section4Config:
    enabled: bool = True
    live_verification_enabled: bool = True
    local_index_enabled: bool = True
    semantic_classifier_enabled: bool = True
    cache_ttl_seconds: int = 21_600
    disclosure_ttl_seconds: int = 86_400
    static_ttl_seconds: int = 604_800
    tender_ttl_seconds: int = 10_800
    max_results_per_source: int = 10
    max_verified_results: int = 5
    request_timeout_seconds: int = 30
    connect_timeout_seconds: int = 10
    total_timeout_seconds: int = 45
    max_html_bytes: int = 10 * 1024 * 1024
    max_pdf_bytes: int = 100 * 1024 * 1024
    max_redirects: int = 3
    max_concurrent_per_domain: int = 2
    requests_per_second_per_domain: float = 1.0
    max_requests_per_domain_per_day: int = 2_000
    circuit_failure_threshold: int = 3
    circuit_cooldown_seconds: int = 300
    playwright_enabled: bool = False
    ocr_enabled: bool = True
    allowed_domains: frozenset[str] = BUILTIN_APPROVED_DOMAINS
    department_domains: frozenset[str] = frozenset()
    user_agent: str = "CHiPS-RTI-Verification/1.0"
    chatbot_team: str = "rti-assistant"
    debug: bool = False
    cache_path: Path = Path("section4_web_verification.sqlite3")
    force_refresh_token: str = ""

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        base_dir: Path | None = None,
    ) -> "Section4Config":
        values = os.environ if env is None else env
        root = base_dir or Path(__file__).resolve().parents[2]
        configured_cache = values.get("SECTION4_CACHE_PATH")
        cache_path = (
            Path(configured_cache).expanduser()
            if configured_cache
            else root / "cache" / "section4_verification.sqlite3"
        )
        if not cache_path.is_absolute():
            cache_path = root / cache_path
        department_domains = _configured_official_domains(
            values.get("SECTION4_DEPARTMENT_DOMAINS")
        )
        min_interval = _as_float(
            values.get("SECTION4_MIN_REQUEST_INTERVAL_SECONDS"),
            1.0,
            minimum=0.5,
            maximum=60.0,
        )
        configured_rps = values.get("SECTION4_REQUESTS_PER_SECOND_PER_DOMAIN")

        return cls(
            enabled=_as_bool(values.get("SECTION4_WEB_VERIFICATION_ENABLED"), True),
            live_verification_enabled=_as_bool(
                values.get("SECTION4_LIVE_VERIFICATION_ENABLED"), True
            ),
            local_index_enabled=_as_bool(
                values.get("SECTION4_LOCAL_INDEX_ENABLED"), True
            ),
            semantic_classifier_enabled=_as_bool(
                values.get("SECTION4_SEMANTIC_CLASSIFIER_ENABLED")
                or values.get("SECTION4_SEMANTIC_TRIGGER_ENABLED"),
                True,
            ),
            cache_ttl_seconds=_as_int(
                values.get("SECTION4_CACHE_TTL_SECONDS"),
                21_600,
                minimum=60,
                maximum=30 * 24 * 60 * 60,
            ),
            disclosure_ttl_seconds=_as_int(
                values.get("SECTION4_DISCLOSURE_TTL_SECONDS"),
                86_400,
                minimum=300,
                maximum=30 * 24 * 60 * 60,
            ),
            static_ttl_seconds=_as_int(
                values.get("SECTION4_STATIC_TTL_SECONDS"),
                604_800,
                minimum=300,
                maximum=90 * 24 * 60 * 60,
            ),
            tender_ttl_seconds=_as_int(
                values.get("SECTION4_TENDER_TTL_SECONDS"),
                10_800,
                minimum=300,
                maximum=7 * 24 * 60 * 60,
            ),
            max_results_per_source=_as_int(
                values.get("SECTION4_MAX_RESULTS_PER_SOURCE"),
                10,
                minimum=1,
                maximum=50,
            ),
            max_verified_results=_as_int(
                values.get("SECTION4_MAX_VERIFIED_RESULTS"),
                5,
                minimum=1,
                maximum=20,
            ),
            request_timeout_seconds=_as_int(
                values.get("SECTION4_REQUEST_TIMEOUT_SECONDS"),
                30,
                minimum=1,
                maximum=120,
            ),
            connect_timeout_seconds=_as_int(
                values.get("SECTION4_CONNECT_TIMEOUT_SECONDS"),
                10,
                minimum=1,
                maximum=30,
            ),
            total_timeout_seconds=_as_int(
                values.get("SECTION4_TOTAL_TIMEOUT_SECONDS"),
                45,
                minimum=5,
                maximum=180,
            ),
            max_html_bytes=_as_int(
                values.get("SECTION4_MAX_HTML_BYTES"),
                10 * 1024 * 1024,
                minimum=1024,
                maximum=50 * 1024 * 1024,
            ),
            max_pdf_bytes=_as_int(
                values.get("SECTION4_MAX_PDF_BYTES"),
                100 * 1024 * 1024,
                minimum=1024,
                maximum=250 * 1024 * 1024,
            ),
            max_redirects=_as_int(
                values.get("SECTION4_MAX_REDIRECTS"), 3, minimum=0, maximum=5
            ),
            max_concurrent_per_domain=_as_int(
                values.get("SECTION4_MAX_CONCURRENT_PER_DOMAIN"),
                2,
                minimum=1,
                maximum=4,
            ),
            requests_per_second_per_domain=_as_float(
                configured_rps,
                1.0 / min_interval,
                minimum=0.1,
                maximum=2.0,
            ),
            max_requests_per_domain_per_day=_as_int(
                values.get("SECTION4_MAX_REQUESTS_PER_DOMAIN_PER_DAY"),
                2_000,
                minimum=1,
                maximum=100_000,
            ),
            circuit_failure_threshold=_as_int(
                values.get("SECTION4_CIRCUIT_FAILURE_THRESHOLD"),
                3,
                minimum=1,
                maximum=20,
            ),
            circuit_cooldown_seconds=_as_int(
                values.get("SECTION4_CIRCUIT_COOLDOWN_SECONDS")
                or values.get("SECTION4_CIRCUIT_RESET_SECONDS"),
                300,
                minimum=30,
                maximum=3600,
            ),
            playwright_enabled=_as_bool(
                values.get("SECTION4_PLAYWRIGHT_ENABLED"), False
            ),
            ocr_enabled=_as_bool(values.get("SECTION4_OCR_ENABLED"), True),
            allowed_domains=_approved_domains(
                values.get("SECTION4_ALLOWED_DOMAINS"),
                values.get("SECTION4_DEPARTMENT_DOMAINS"),
            ),
            department_domains=department_domains,
            user_agent=(
                values.get("SECTION4_USER_AGENT", "CHiPS-RTI-Verification/1.0")
                .strip()[:200]
                or "CHiPS-RTI-Verification/1.0"
            ),
            chatbot_team=(
                values.get("SECTION4_CHATBOT_TEAM", "rti-assistant").strip()[:160]
                or "rti-assistant"
            ),
            debug=_as_bool(values.get("SECTION4_DEBUG"), False),
            cache_path=cache_path,
            force_refresh_token=values.get("SECTION4_FORCE_REFRESH_TOKEN", "").strip(),
        )
