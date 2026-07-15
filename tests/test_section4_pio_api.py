from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
WEBUI_DIR = ROOT / "FG" / "05_webui"
sys.path.insert(0, str(WEBUI_DIR))

import app as web_app  # noqa: E402


def _verification_result(
    status: str = "FOUND",
    *,
    triggered: bool = True,
) -> dict:
    found = status in {"FOUND", "PARTIALLY_FOUND"}
    unavailable = status == "SOURCE_UNAVAILABLE"
    return {
        "verification_id": "verification-123",
        "triggered": triggered,
        "trigger_reason": (
            "Explicit Section 4(1)(b) reference"
            if triggered
            else "No material Section 4(1)(b) trigger was established."
        ),
        "trigger_source": "EXPLICIT_REFERENCE" if triggered else "NONE",
        "sub_clause": "xv" if triggered else None,
        "status": status,
        "organisation": "Public Works Department" if triggered else None,
        "subject": "Tender NIT-123" if triggered else None,
        "searched_sources": (
            [
                {
                    "adapter_id": "cg_eproc_current",
                    "domain": "cgeproc.cgstate.gov.in",
                    "status": "SUCCESS" if found else "UNAVAILABLE",
                    "results_examined": 1 if found else 0,
                    "candidates_found": 1 if found else 0,
                    "elapsed_ms": 4,
                    "error_code": "SOURCE_TIMEOUT" if unavailable else None,
                }
            ]
            if triggered
            else []
        ),
        "found_items": (
            [
                {
                    "evidence_id": "evidence-123",
                    "title": "Official tender notice",
                    "url": "https://cgeproc.cgstate.gov.in/nicgep/app",
                    "domain": "cgeproc.cgstate.gov.in",
                    "document_type": "tender",
                    "publication_date": "2026-07-01",
                    "page_number": 1,
                    "section_heading": "Latest Active Tenders",
                    "matched_text": "NIT-123 Public Works Department",
                    "matched_entities": ["NIT-123"],
                    "supported_fields": ["tender_number"],
                    "relevance_score": 0.95,
                    "verified": True,
                    "document_hash": "abc123",
                }
            ]
            if found
            else []
        ),
        "available_fields": ["tender_number"] if found else [],
        "missing_fields": ["payment_details"] if triggered else [],
        "verification_timestamp": "2026-07-14T06:00:00+00:00",
        "warnings": (
            ["One or more approved sources were unavailable."]
            if unavailable
            else []
        ),
        "errors": (
            [{"code": "SOURCE_TIMEOUT", "message": "Approved source timed out."}]
            if unavailable
            else []
        ),
        "cache_hit": False,
        "cached": False,
    }


class FakeSection4Service:
    def __init__(self) -> None:
        self.config = SimpleNamespace(force_refresh_token="")
        self.verify_result = _verification_result()
        self.sources_result = {
            "verification_id": "verification-123",
            "status": "FOUND",
            "found_items": self.verify_result["found_items"],
            "verification_timestamp": "2026-07-14T06:00:00+00:00",
        }
        self.retry_result = _verification_result("PARTIALLY_FOUND")
        self.health_result = {
            "enabled": True,
            "live_verification_enabled": True,
            "local_index_enabled": True,
            "cache": "ready",
            "sources": [
                {
                    "adapter_id": "cic_disclosures",
                    "domain": "cic.gov.in",
                    "enabled": True,
                    "status": "READY",
                    "checked_at": None,
                    "error_code": None,
                }
            ],
        }
        self.verify_error: Exception | None = None
        self.sources_error: Exception | None = None
        self.retry_error: Exception | None = None
        self.health_error: Exception | None = None
        self.verify_calls: list[dict] = []
        self.source_calls: list[str] = []
        self.retry_calls: list[str] = []

    def verify(self, **kwargs):
        self.verify_calls.append(kwargs)
        if self.verify_error is not None:
            raise self.verify_error
        return self.verify_result

    def sources(self, verification_id: str):
        self.source_calls.append(verification_id)
        if self.sources_error is not None:
            raise self.sources_error
        return self.sources_result

    def retry(self, verification_id: str):
        self.retry_calls.append(verification_id)
        if self.retry_error is not None:
            raise self.retry_error
        return self.retry_result

    def health(self):
        if self.health_error is not None:
            raise self.health_error
        return self.health_result


@pytest.fixture
def service() -> FakeSection4Service:
    return FakeSection4Service()


@pytest.fixture
def client(monkeypatch, service):
    monkeypatch.setattr(
        web_app,
        "_section4_verification_service",
        lambda: service,
    )
    web_app.app.config.update(TESTING=True)
    with web_app.app.test_client() as test_client:
        yield test_client


def test_section4_post_success_shape_and_forwards_only_structured_inputs(
    client,
    service,
):
    response = client.post(
        "/api/web-verification/section-4",
        json={
            "query": "Verify Section 4(1)(b)(xv) disclosure for NIT-123.",
            "rti_extraction": {"public_authority": "Public Works Department"},
            "legal_analysis": {
                "point_analysis": [
                    {"applicable_provisions": ["4(1)(b)(xv)"]}
                ]
            },
            "force_refresh": False,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "FOUND"
    assert payload["triggered"] is True
    assert payload["verification_id"] == "verification-123"
    assert payload["found_items"][0]["verified"] is True
    assert payload["found_items"][0]["domain"] == "cgeproc.cgstate.gov.in"
    assert service.verify_calls == [
        {
            "query": "Verify Section 4(1)(b)(xv) disclosure for NIT-123.",
            "rti_extraction": {"public_authority": "Public Works Department"},
            "legal_analysis": {
                "point_analysis": [
                    {"applicable_provisions": ["4(1)(b)(xv)"]}
                ]
            },
            "force_refresh": False,
        }
    ]


def test_section4_post_not_triggered_shape(client, service):
    service.verify_result = _verification_result(
        "SEARCH_NOT_TRIGGERED",
        triggered=False,
    )

    response = client.post(
        "/api/web-verification/section-4",
        json={"query": "What is the Section 7 response time?"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["triggered"] is False
    assert payload["status"] == "SEARCH_NOT_TRIGGERED"
    assert payload["searched_sources"] == []
    assert payload["found_items"] == []


def test_section4_post_can_use_server_cached_advisory_context(
    client,
    service,
    monkeypatch,
):
    monkeypatch.setattr(
        web_app,
        "_get_pio_advisory",
        lambda advisory_id: {
            "rti_text": "Verify Section 4(1)(b)(xv) disclosure for NIT-123.",
            "rti_extraction": {"public_authority": "Public Works Department"},
            "legal_analysis": {"point_analysis": [{"applicable_provisions": ["4(1)(b)(xv)"]}]},
        } if advisory_id == "advisory-123" else None,
    )

    response = client.post(
        "/api/web-verification/section-4",
        json={"advisory_id": "advisory-123", "query": "untrusted override"},
    )

    assert response.status_code == 200
    assert service.verify_calls[-1]["query"].startswith("Verify Section 4")
    assert service.verify_calls[-1]["rti_extraction"] == {
        "public_authority": "Public Works Department"
    }


def test_section4_post_verifier_exception_is_structured_source_unavailable(
    client,
    service,
):
    service.verify_error = RuntimeError("must not leak")

    response = client.post(
        "/api/web-verification/section-4",
        json={"query": "Verify Section 4(1)(b) disclosure."},
    )

    assert response.status_code == 503
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["triggered"] is True
    assert payload["status"] == "SOURCE_UNAVAILABLE"
    assert payload["found_items"] == []
    assert payload["errors"] == [
        {
            "code": "VERIFIER_UNAVAILABLE",
            "message": "The restricted verifier could not run safely.",
        }
    ]
    assert "must not leak" not in response.get_data(as_text=True)


@pytest.mark.parametrize(
    ("request_kwargs", "expected_status", "expected_error"),
    [
        ({"data": "not-json", "content_type": "text/plain"}, 400, "JSON request"),
        ({"json": {}}, 400, "query is required"),
        ({"json": {"query": " "}}, 400, "query is required"),
        ({"json": {"query": "x" * 50_001}}, 413, "50000 character limit"),
        (
            {"json": {"query": "Section 4(1)(b)", "rti_extraction": []}},
            400,
            "must be JSON objects",
        ),
        (
            {"json": {"query": "Section 4(1)(b)", "legal_analysis": []}},
            400,
            "must be JSON objects",
        ),
    ],
)
def test_section4_post_validates_request(
    client,
    service,
    request_kwargs,
    expected_status,
    expected_error,
):
    response = client.post(
        "/api/web-verification/section-4",
        **request_kwargs,
    )

    assert response.status_code == expected_status
    assert response.get_json()["success"] is False
    assert expected_error in response.get_json()["error"]
    assert service.verify_calls == []


def test_force_refresh_rejects_blank_and_wrong_token_then_accepts_correct_header(
    client,
    service,
):
    body = {
        "query": "Verify Section 4(1)(b) disclosure.",
        "force_refresh": True,
    }

    service.config.force_refresh_token = ""
    blank = client.post(
        "/api/web-verification/section-4",
        json=body,
        headers={"X-Section4-Force-Refresh-Token": "anything"},
    )
    assert blank.status_code == 403
    assert blank.get_json() == {
        "success": False,
        "error": "force_refresh is not authorised.",
    }

    service.config.force_refresh_token = "correct-secret"
    wrong = client.post(
        "/api/web-verification/section-4",
        json=body,
        headers={"X-Section4-Force-Refresh-Token": "wrong-secret"},
    )
    assert wrong.status_code == 403

    accepted = client.post(
        "/api/web-verification/section-4",
        json=body,
        headers={"X-Section4-Force-Refresh-Token": "correct-secret"},
    )
    assert accepted.status_code == 200
    assert accepted.get_json()["status"] == "FOUND"
    assert service.verify_calls == [
        {
            "query": "Verify Section 4(1)(b) disclosure.",
            "rti_extraction": {},
            "legal_analysis": {},
            "force_refresh": True,
        }
    ]


def test_sources_endpoint_returns_verified_sources_and_404(client, service):
    response = client.get(
        "/api/web-verification/sources/verification-123"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["verification_id"] == "verification-123"
    assert payload["found_items"][0]["verified"] is True
    assert service.source_calls == ["verification-123"]

    service.sources_result = None
    missing = client.get("/api/web-verification/sources/missing")
    assert missing.status_code == 404
    assert missing.get_json() == {
        "success": False,
        "error": "Verification result was not found or has expired.",
    }


def test_retry_endpoint_returns_result_404_and_structured_failure(
    client,
    service,
):
    response = client.post(
        "/api/web-verification/verification-123/retry",
        json={"answer_language": "hi"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "PARTIALLY_FOUND"
    assert service.retry_calls == ["verification-123"]

    service.retry_result = None
    missing = client.post("/api/web-verification/missing/retry", json={})
    assert missing.status_code == 404
    assert missing.get_json()["success"] is False

    service.retry_error = RuntimeError("must not leak")
    failed = client.post("/api/web-verification/again/retry", json={})
    assert failed.status_code == 503
    failure = failed.get_json()
    assert failure["success"] is False
    assert failure["verification_id"] == "again"
    assert failure["status"] == "SOURCE_UNAVAILABLE"
    assert failure["errors"][0]["code"] == "RETRY_FAILED"
    assert "must not leak" not in failed.get_data(as_text=True)


def test_health_endpoint_returns_service_snapshot_and_sanitized_failure(
    client,
    service,
):
    response = client.get("/api/web-verification/health")

    assert response.status_code == 200
    assert response.get_json() == service.health_result

    service.health_error = RuntimeError("private health detail")
    failed = client.get("/api/web-verification/health")
    assert failed.status_code == 503
    assert failed.get_json() == {
        "enabled": False,
        "status": "SOURCE_UNAVAILABLE",
        "cache": "unavailable",
        "sources": [],
    }
    assert "private health detail" not in failed.get_data(as_text=True)
