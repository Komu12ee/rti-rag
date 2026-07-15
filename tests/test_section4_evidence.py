from dataclasses import replace
from pathlib import Path
import sys


WEBUI = Path(__file__).resolve().parents[1] / "FG" / "05_webui"
if str(WEBUI) not in sys.path:
    sys.path.insert(0, str(WEBUI))

from services.section4_web_verification.config import Section4Config
from services.section4_web_verification.evidence_validator import (
    validate_document_evidence,
)
from services.section4_web_verification.result_merger import merge_verification_result
from services.section4_web_verification.schemas import (
    DocumentPage,
    EntityRef,
    RetrievedDocument,
    SearchPlan,
    Section4TriggerResult,
    SearchedSource,
    SourceSearchStatus,
    TenderIntent,
    TriggerSource,
    VerificationStatus,
)


def config() -> Section4Config:
    return Section4Config(
        allowed_domains=frozenset({"cgeproc.cgstate.gov.in", "chips.gov.in"}),
        ocr_enabled=False,
    )


def plan(*fields: str) -> SearchPlan:
    return SearchPlan(
        organisation=EntityRef(
            name="Chhattisgarh Infotech Promotion Society",
            aliases=("CHiPS", "CHIPS"),
        ),
        company=EntityRef(
            name="Tata Projects Limited",
            aliases=("Tata Projects", "TPL"),
        ),
        project=EntityRef(
            name="BharatNet Phase-II",
            aliases=("BharatNet Phase 2",),
        ),
        requested_fields=tuple(fields),
        tender=TenderIntent(tender_intent=True, intent_type="PAYMENT_SEARCH"),
    )


def document(text: str, *, domain: str = "cgeproc.cgstate.gov.in", title: str = "Tender award") -> RetrievedDocument:
    return RetrievedDocument(
        title=title,
        url=f"https://{domain}/nicgep/document.pdf",
        final_url=f"https://{domain}/nicgep/document.pdf",
        domain=domain,
        source_type="pdf",
        retrieved_at="2026-07-14T05:00:00+00:00",
        content_type="application/pdf",
        document_hash="a" * 64,
        pages=(DocumentPage(page_number=4, text=text),),
    )


def trigger() -> Section4TriggerResult:
    return Section4TriggerResult(
        triggered=True,
        trigger_type="SECTION_4_1_B",
        trigger_source=TriggerSource.LEGAL_ANALYSIS,
        confidence=0.95,
        reason="Section 4 applies",
        tender_intent=True,
    )


def searched(status: SourceSearchStatus = SourceSearchStatus.SUCCESS) -> tuple[SearchedSource, ...]:
    return (
        SearchedSource(
            adapter_id="cg_eproc",
            domain="cgeproc.cgstate.gov.in",
            status=status,
            results_examined=1,
        ),
    )


def test_tender_terms_do_not_prove_actual_payments():
    value = document(
        "CHiPS invited a tender for Tata Projects Limited, BharatNet Phase-II. "
        "Tender No 123 and Contract Value Rs 10 crore. Payment terms mention "
        "monthly payment, deductions and outstanding amounts."
    )
    evidence = validate_document_evidence(
        value,
        plan("monthly_payments", "deductions", "outstanding_amount"),
        config(),
    )

    assert evidence
    assert evidence[0].verified is True
    assert "contract_value" in evidence[0].supported_fields
    assert "monthly_payments" not in evidence[0].supported_fields
    assert "deductions" not in evidence[0].supported_fields
    assert evidence[0].page_number == 4

    result = merge_verification_result(
        trigger(),
        plan("monthly_payments", "deductions", "outstanding_amount"),
        searched(),
        evidence,
    )
    assert result.status == VerificationStatus.PARTIALLY_FOUND
    assert set(result.missing_fields) == {
        "monthly_payments",
        "deductions",
        "outstanding_amount",
    }


def test_execution_record_can_support_payment_fields():
    value = document(
        "CHiPS payment ledger for Tata Projects Limited, BharatNet Phase-II. "
        "Amount paid on 01-06-2026. Monthly payment Rs 4 lakh; deduction Rs 5,000; "
        "outstanding amount Rs 20,000.",
        title="Payment ledger",
    )
    requested = plan("monthly_payments", "deductions", "outstanding_amount")
    evidence = validate_document_evidence(value, requested, config())
    assert evidence
    assert set(requested.requested_fields) <= set(evidence[0].supported_fields)
    result = merge_verification_result(trigger(), requested, searched(), evidence)
    assert result.status == VerificationStatus.FOUND
    assert result.missing_fields == ()


def test_unapproved_url_cannot_be_evidence():
    value = document(
        "CHiPS Tata Projects Limited BharatNet Phase-II amount paid monthly payment.",
        domain="example.com",
        title="Payment ledger",
    )
    assert validate_document_evidence(value, plan("monthly_payments"), config()) == []


def test_missing_entity_and_passage_cannot_be_found():
    value = document("Generic tender navigation and links with no matching organisation.")
    evidence = validate_document_evidence(value, plan("tender_number"), config())
    result = merge_verification_result(trigger(), plan("tender_number"), searched(), evidence)
    assert evidence == []
    assert result.status == VerificationStatus.NOT_FOUND


def test_every_planned_entity_must_match_before_evidence_is_verified():
    unrelated_project = document(
        "CHiPS payment ledger for Tata Projects Limited. Amount paid on 01-06-2024. "
        "Monthly payment Rs 4 lakh.",
        title="Unrelated project payment ledger",
    )

    assert validate_document_evidence(
        unrelated_project,
        plan("monthly_payments"),
        config(),
    ) == []


def test_requested_date_range_must_match_document_or_passage_date():
    requested = replace(
        plan("monthly_payments"),
        date_from="2024-01-01",
        date_to="2024-12-31",
    )
    old = document(
        "CHiPS payment ledger for Tata Projects Limited, BharatNet Phase-II. "
        "Amount paid on 01-06-2020. Monthly payment Rs 4 lakh.",
        title="Payment ledger",
    )
    current = document(
        "CHiPS payment ledger for Tata Projects Limited, BharatNet Phase-II. "
        "Amount paid on 01-06-2024. Monthly payment Rs 4 lakh.",
        title="Payment ledger",
    )

    assert validate_document_evidence(old, requested, config()) == []
    assert validate_document_evidence(current, requested, config())


def test_unavailable_source_returns_source_unavailable():
    result = merge_verification_result(
        trigger(),
        plan("monthly_payments"),
        searched(SourceSearchStatus.UNAVAILABLE),
        [],
    )
    assert result.status == VerificationStatus.SOURCE_UNAVAILABLE
    assert result.errors[0]["code"] == "SOURCE_UNAVAILABLE"
