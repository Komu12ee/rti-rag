import asyncio
import json
import sqlite3
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WEBUI_DIR = ROOT / "FG" / "05_webui"
sys.path.insert(0, str(WEBUI_DIR))

from services.section4_web_verification.audit import (  # noqa: E402
    Section4AuditLogger,
    query_sha256,
)
from services.section4_web_verification.cache import Section4Cache  # noqa: E402
from services.section4_web_verification.config import Section4Config  # noqa: E402
from services.section4_web_verification.rate_limiter import (  # noqa: E402
    CircuitOpenError,
    DailyRequestLimitError,
    DomainRateLimiter,
    SyncDomainRateLimiter,
)
from services.section4_web_verification.schemas import (  # noqa: E402
    DocumentPage,
    EvidenceItem,
    RetrievedDocument,
    SearchedSource,
    SourceSearchStatus,
    TriggerSource,
    VerificationResult,
    VerificationStatus,
)


class FakeClock:
    def __init__(self, value: float = 100.0):
        self.value = value
        self.delays: list[float] = []

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds

    def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)
        self.advance(seconds)

    async def async_sleep(self, seconds: float) -> None:
        self.sleep(seconds)
        await asyncio.sleep(0)


def _config(tmp_path: Path, **changes) -> Section4Config:
    base = Section4Config(
        cache_path=tmp_path / "section4-cache.sqlite3",
        cache_ttl_seconds=10,
        requests_per_second_per_domain=1000.0,
        max_concurrent_per_domain=2,
        circuit_failure_threshold=3,
        circuit_cooldown_seconds=1,
    )
    return replace(base, **changes)


def _document() -> RetrievedDocument:
    return RetrievedDocument(
        source_id="document-1",
        title="BharatNet Phase-II contract and payment details",
        url="https://cic.gov.in/public/document?id=1",
        final_url="https://www.cic.gov.in/public/document-1.pdf",
        domain="www.cic.gov.in",
        source_type="decision",
        publication_date="2026-07-14",
        retrieved_at="2026-07-14T10:30:00+05:30",
        content_type="application/pdf",
        pages=(
            DocumentPage(
                page_number=1,
                text="CHiPS BharatNet contract value and selected agency Tata Projects.",
            ),
            DocumentPage(
                page_number=2,
                text="The public document does not contain monthly payment details.",
            ),
        ),
        http_status=200,
        byte_count=2048,
        etag='"etag-1"',
        last_modified="Tue, 14 Jul 2026 05:00:00 GMT",
        extraction_method="pymupdf",
    )


def _verification_result() -> VerificationResult:
    return VerificationResult(
        verification_id="verification-1",
        triggered=True,
        trigger_reason="SECTION_4_1_B",
        trigger_source=TriggerSource.EXPLICIT_REFERENCE,
        sub_clause="xv",
        status=VerificationStatus.PARTIALLY_FOUND,
        organisation="CHiPS",
        subject="BharatNet payment disclosure",
        searched_sources=(
            SearchedSource(
                adapter_id="cic",
                domain="cic.gov.in",
                status=SourceSearchStatus.SUCCESS,
                results_examined=2,
                candidates_found=1,
            ),
        ),
        found_items=(
            EvidenceItem(
                evidence_id="evidence-1",
                title="BharatNet contract",
                url="https://cic.gov.in/public/document-1.pdf",
                domain="cic.gov.in",
                document_type="decision",
                page_number=1,
                matched_text="BharatNet contract value",
                supported_fields=("contract_value",),
                relevance_score=0.91,
                verified=True,
                document_hash="abc123",
            ),
        ),
        available_fields=("contract_value",),
        missing_fields=("monthly_payments",),
        verification_timestamp="2026-07-14T10:30:00+05:30",
    )


def test_cache_auto_initializes_wal_and_expires_hashed_query_results(tmp_path):
    clock = FakeClock()
    config = _config(tmp_path)
    cache = Section4Cache(config, now=clock)

    cache_key = cache.put_query_result(
        "Private RTI wording that must not be a database key",
        _verification_result(),
        ttl_seconds=2,
    )

    assert len(cache_key) == 64
    assert cache.get_query_result("Private RTI wording that must not be a database key")[
        "status"
    ] == "PARTIALLY_FOUND"

    with sqlite3.connect(config.cache_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].casefold() == "wal"
        stored_key = connection.execute("SELECT cache_key FROM query_results").fetchone()[0]
    assert stored_key == cache_key
    assert "Private RTI" not in stored_key

    clock.advance(2.001)
    assert cache.get_query_result(cache_key) is None


def test_document_cache_preserves_conditional_metadata_search_and_stale_304_body(tmp_path):
    clock = FakeClock()
    cache = Section4Cache(_config(tmp_path), now=clock)
    document = _document()

    document_hash = cache.put_document(document, ttl_seconds=1)
    cached = cache.get_document(document.url)
    metadata = cache.get_document_metadata(document.url)
    hits = cache.search_documents("BharatNet contract value", limit=3)

    assert cached is not None
    assert cached.document_hash == document_hash
    assert metadata["etag"] == '"etag-1"'
    assert metadata["last_modified"].startswith("Tue, 14 Jul")
    assert metadata["document_hash"] == document_hash
    assert metadata["url"] == document.url
    assert metadata["final_url"] == document.final_url
    assert cache.get_document_by_hash(document_hash).source_id == "document-1"
    assert hits and hits[0].document.source_id == "document-1"
    assert "bharatnet" in hits[0].matched_terms
    assert cache.search_documents("unrelated phrase") == []

    clock.advance(1.001)
    assert cache.get_document(document.url) is None
    assert cache.get_document(document.url, include_expired=True) is not None
    assert cache.get_document_metadata(document.url)["is_expired"] is True

    assert cache.touch_document(document.url, ttl_seconds=5) is True
    assert cache.get_document(document.url) is not None
    assert cache.get_document_metadata(document.url)["is_expired"] is False


def test_verification_result_and_public_retry_context_persist_with_ttl(tmp_path):
    clock = FakeClock()
    cache = Section4Cache(_config(tmp_path), now=clock)
    context = {
        "search_plan": {
            "organisation": "CHiPS",
            "search_queries": ["CHiPS BharatNet contract"],
        },
        "failed_adapters": ["cic"],
    }

    cache.put_verification_result(
        _verification_result(),
        context=context,
        query_cache_key="Section 4 query",
        ttl_seconds=3,
    )
    restored = cache.get_verification_result("verification-1")
    retry_context = cache.get_verification_context("verification-1")

    assert restored.status is VerificationStatus.PARTIALLY_FOUND
    assert restored.found_items[0].verified is True
    assert retry_context["search_plan"] == context["search_plan"]
    assert retry_context["query_cache_key"] == cache.query_cache_key("Section 4 query")

    with pytest.raises(ValueError, match="Sensitive field"):
        cache.put_verification_result(
            _verification_result(),
            context={"rti_text": "private application body"},
        )

    clock.advance(3.001)
    assert cache.get_verification_result("verification-1") is None
    assert cache.get_verification_context("verification-1") is None


def test_sync_rate_limiter_paces_exact_domains_with_bounded_backoff(tmp_path):
    clock = FakeClock()
    limiter = SyncDomainRateLimiter(
        _config(tmp_path),
        base_backoff_seconds=0.001,
        max_backoff_seconds=0.003,
        clock=clock,
        sleep=clock.sleep,
    )

    with limiter.slot("CIC.GOV.IN."):
        pass
    with limiter.slot("cic.gov.in"):
        pass
    same_domain_delays = list(clock.delays)
    with limiter.slot("www.cic.gov.in"):
        pass

    assert same_domain_delays == pytest.approx([0.001])
    assert clock.delays == same_domain_delays
    assert limiter.backoff_delay(1) == pytest.approx(0.001)
    assert limiter.backoff_delay(2) == pytest.approx(0.002)
    assert limiter.backoff_delay(3) == pytest.approx(0.003)
    assert limiter.backoff_delay(20) == pytest.approx(0.003)
    for invalid in (
        "https://cic.gov.in",
        "cic.gov.in:443",
        "user@cic.gov.in",
        ".cic.gov.in",
    ):
        with pytest.raises(ValueError, match="exact hostname"):
            limiter.normalize_domain(invalid)


def test_sync_rate_limiter_retry_and_circuit_breaker_use_fake_millisecond_clock(tmp_path):
    clock = FakeClock()
    limiter = SyncDomainRateLimiter(
        _config(
            tmp_path,
            circuit_failure_threshold=4,
            circuit_cooldown_seconds=0.005,
        ),
        base_backoff_seconds=0.001,
        max_backoff_seconds=0.002,
        max_attempts=3,
        clock=clock,
        sleep=clock.sleep,
    )
    attempts = 0

    def operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("temporary source failure")
        return "ok"

    assert limiter.run("cic.gov.in", operation) == "ok"
    assert attempts == 3
    assert all(delay <= 0.002 for delay in clock.delays)

    limiter.record_failure("gem.gov.in")
    limiter.record_failure("gem.gov.in")
    limiter.record_failure("gem.gov.in")
    limiter.record_failure("gem.gov.in")
    assert limiter.snapshot("gem.gov.in")["circuit_open"] is True
    with pytest.raises(CircuitOpenError):
        with limiter.slot("gem.gov.in"):
            pass
    clock.advance(0.006)
    with limiter.slot("gem.gov.in"):
        pass
    assert limiter.snapshot("gem.gov.in")["circuit_open"] is False


def test_daily_per_domain_budget_is_counted_enforced_and_resets(tmp_path):
    day = {"value": "2026-07-14"}
    limiter = SyncDomainRateLimiter(
        _config(tmp_path, max_requests_per_domain_per_day=2),
        day_key=lambda: day["value"],
        sleep=lambda _seconds: None,
    )

    with limiter.slot("cic.gov.in"):
        pass
    with limiter.slot("cic.gov.in"):
        pass
    with pytest.raises(DailyRequestLimitError):
        with limiter.slot("cic.gov.in"):
            pass
    snapshot = limiter.snapshot("cic.gov.in")
    assert snapshot["request_day"] == "2026-07-14"
    assert snapshot["requests_today"] == 2
    assert snapshot["daily_request_limit"] == 2

    day["value"] = "2026-07-15"
    with limiter.slot("cic.gov.in"):
        pass
    assert limiter.snapshot("cic.gov.in")["requests_today"] == 1


def test_async_rate_limiter_has_same_exact_domain_and_circuit_contract(tmp_path):
    async def scenario():
        clock = FakeClock()
        limiter = DomainRateLimiter(
            _config(
                tmp_path,
                circuit_failure_threshold=1,
                circuit_cooldown_seconds=0.004,
            ),
            base_backoff_seconds=0.001,
            max_backoff_seconds=0.002,
            clock=clock,
            sleep=clock.async_sleep,
        )

        async with limiter.slot("cic.gov.in"):
            pass
        async with limiter.slot("cic.gov.in"):
            pass
        assert clock.delays == pytest.approx([0.001])

        await limiter.record_failure("gem.gov.in")
        assert (await limiter.snapshot("gem.gov.in"))["circuit_open"] is True
        with pytest.raises(CircuitOpenError):
            async with limiter.slot("gem.gov.in"):
                pass
        clock.advance(0.005)
        async with limiter.slot("gem.gov.in"):
            pass
        assert (await limiter.snapshot("gem.gov.in"))["circuit_open"] is False

    asyncio.run(scenario())


def test_audit_log_is_json_and_hashes_queries_without_bodies_or_credentials():
    class CapturingLogger:
        def __init__(self):
            self.messages: list[str] = []

        def info(self, message: str) -> None:
            self.messages.append(message)

    logger = CapturingLogger()
    audit = Section4AuditLogger(
        logger,
        now=lambda: datetime(2026, 7, 14, 5, 0, tzinfo=timezone.utc),
        chatbot_team="rti-assistant",
    )
    raw_query = "private RTI application secret-xyz"
    payload = audit.emit(
        "source_fetch_completed",
        request_id="request-1",
        verification_id="verification-1",
        query=raw_query,
        requested_url="https://user:password@cic.gov.in/public/doc?token=secret#private",
        selected_sources=[{"domain": "CIC.GOV.IN"}],
        generated_search_terms=["CHiPS BharatNet secret search"],
        http_status=200,
        byte_count=2048,
        body="private body must never be logged",
        authorization="Bearer secret-token",
        error="raw exception text",
    )

    encoded = logger.messages[0]
    decoded = json.loads(encoded)
    assert decoded == payload
    assert decoded["chatbot_team"] == "rti-assistant"
    assert decoded["query_sha256"] == query_sha256(raw_query)
    assert decoded["requested_url"] == "https://cic.gov.in/public/doc"
    assert decoded["selected_sources"] == ["cic.gov.in"]
    assert decoded["http_status"] == 200
    assert "body" not in decoded
    assert "authorization" not in decoded
    assert "error" not in decoded
    assert raw_query not in encoded
    assert "secret-xyz" not in encoded
    assert "password" not in encoded
    assert "secret-token" not in encoded
