from dataclasses import replace
from pathlib import Path
import sys
import time


WEBUI = Path(__file__).resolve().parents[1] / "FG" / "05_webui"
if str(WEBUI) not in sys.path:
    sys.path.insert(0, str(WEBUI))

from services.section4_web_verification.adapters import AdapterError, BaseSourceAdapter
from services.section4_web_verification.cache import Section4Cache
from services.section4_web_verification.config import Section4Config
from services.section4_web_verification.orchestrator import Section4VerificationService
from services.section4_web_verification.schemas import (
    DocumentPage,
    RetrievedDocument,
    SearchCandidate,
    SourceHealth,
)


class FakeRegistry:
    def __init__(self, adapter):
        self.adapter = adapter

    def select(self, *_args, **_kwargs):
        return (self.adapter,)

    def health_check(self):
        return (self.adapter.health_check(),)


class FakeAdapter(BaseSourceAdapter):
    adapter_id = "sci_public"
    domain = "chips.gov.in"
    enabled = True

    def __init__(self, document=None, error_code=None):
        self.document = document
        self.error_code = error_code
        self.search_calls = 0
        self.fetch_calls = 0

    def search(self, _plan):
        self.search_calls += 1
        if self.error_code == "SEARCH_FAILED":
            raise AdapterError("SEARCH_FAILED", "unavailable")
        return [
            SearchCandidate(
                adapter_id=self.adapter_id,
                url="https://chips.gov.in/section4/remuneration.html",
                title="Section 4 disclosure",
            )
        ]

    def fetch(self, _candidate):
        self.fetch_calls += 1
        if self.error_code:
            raise AdapterError(self.error_code, "unavailable")
        return self.document

    def health_check(self):
        return SourceHealth(
            adapter_id=self.adapter_id,
            domain=self.domain,
            enabled=True,
            status="ready" if not self.error_code else "degraded",
            error_code=self.error_code,
        )


class SlowSearchAdapter(FakeAdapter):
    def search(self, plan):
        time.sleep(0.15)
        return super().search(plan)


def disclosure_document():
    return RetrievedDocument(
        title="CHiPS monthly remuneration disclosure",
        url="https://chips.gov.in/section4/remuneration.html",
        final_url="https://chips.gov.in/section4/remuneration.html",
        domain="chips.gov.in",
        source_type="html",
        publication_date="2026-07-01",
        retrieved_at="2026-07-14T05:00:00+00:00",
        content_type="text/html",
        document_hash="b" * 64,
        pages=(
            DocumentPage(
                page_number=1,
                section_headings=("Section 4(1)(b)(x)",),
                text=(
                    "CHiPS (Chhattisgarh Infotech Promotion Society) proactive disclosure. "
                    "Section 4(1)(b)(x): monthly remuneration and pay scale of officers."
                ),
            ),
        ),
        http_status=200,
        byte_count=500,
        extraction_method="test",
    )


def build_service(tmp_path, adapter):
    config = Section4Config(
        semantic_classifier_enabled=False,
        allowed_domains=frozenset({"chips.gov.in"}),
        cache_path=tmp_path / "section4.sqlite3",
        max_results_per_source=2,
        max_verified_results=2,
        ocr_enabled=False,
    )
    cache = Section4Cache(config)
    return Section4VerificationService(
        config,
        cache=cache,
        registry=FakeRegistry(adapter),
    )


def extraction():
    return {
        "public_authority": "CHiPS",
        "information_points": [
            {
                "requested_information": "monthly remuneration of officers",
                "record_types_requested": ["remuneration statement"],
            }
        ],
    }


def test_orchestrator_returns_verified_found_result(tmp_path):
    adapter = FakeAdapter(disclosure_document())
    service = build_service(tmp_path, adapter)
    result = service.verify(
        "Verify Section 4(1)(b)(x) monthly remuneration disclosure for CHiPS",
        extraction(),
        {},
    )

    assert result["status"] == "FOUND"
    assert result["triggered"] is True
    assert result["sub_clause"] == "x"
    assert result["found_items"][0]["verified"] is True
    assert result["found_items"][0]["url"].startswith("https://chips.gov.in/")
    assert result["found_items"][0]["page_number"] == 1
    assert result["cached"] is False


def test_no_trigger_never_calls_source(tmp_path):
    adapter = FakeAdapter(disclosure_document())
    service = build_service(tmp_path, adapter)
    result = service.verify("What is the Section 7 response time?", {}, {})

    assert result["status"] == "SEARCH_NOT_TRIGGERED"
    assert adapter.search_calls == 0
    assert adapter.fetch_calls == 0


def test_source_failure_is_structured_and_does_not_invent_evidence(tmp_path):
    adapter = FakeAdapter(error_code="HTTP_TIMEOUT")
    service = build_service(tmp_path, adapter)
    result = service.verify("Section 4(1)(b)(x) CHiPS monthly remuneration", extraction(), {})

    assert result["status"] == "SOURCE_UNAVAILABLE"
    assert result["found_items"] == []
    assert result["errors"][0]["code"] == "HTTP_TIMEOUT"


def test_query_result_cache_avoids_duplicate_source_fetch(tmp_path):
    adapter = FakeAdapter(disclosure_document())
    service = build_service(tmp_path, adapter)
    first = service.verify("Section 4(1)(b)(x) CHiPS monthly remuneration", extraction(), {})
    second = service.verify("Section 4(1)(b)(x) CHiPS monthly remuneration", extraction(), {})

    assert first["status"] == "FOUND"
    assert second["status"] == "FOUND"
    assert second["cached"] is True
    assert adapter.search_calls == 1
    assert adapter.fetch_calls == 1


def test_retry_uses_saved_public_plan_and_same_verification_id(tmp_path):
    adapter = FakeAdapter(error_code="HTTP_TIMEOUT")
    service = build_service(tmp_path, adapter)
    first = service.verify("Section 4(1)(b)(x) CHiPS monthly remuneration", extraction(), {})
    adapter.error_code = None
    adapter.document = disclosure_document()

    retried = service.retry(first["verification_id"])
    assert retried is not None
    assert retried["verification_id"] == first["verification_id"]
    assert retried["status"] == "FOUND"


def test_health_is_per_adapter_and_does_not_fetch(tmp_path):
    adapter = FakeAdapter(disclosure_document())
    service = build_service(tmp_path, adapter)
    health = service.health()
    assert health["cache"] == "ready"
    assert health["sources"][0]["adapter_id"] == "sci_public"
    assert adapter.fetch_calls == 0


def test_overall_deadline_returns_without_waiting_for_every_source(tmp_path):
    adapter = SlowSearchAdapter(disclosure_document())
    service = build_service(tmp_path, adapter)
    service.config = replace(service.config, total_timeout_seconds=0.02)

    started = time.perf_counter()
    result = service.verify(
        "Section 4(1)(b)(x) CHiPS monthly remuneration",
        extraction(),
        {},
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 0.12
    assert result["status"] == "SOURCE_UNAVAILABLE"
    assert result["errors"][0]["code"] == "VERIFICATION_DEADLINE"
