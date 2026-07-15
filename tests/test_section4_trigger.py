import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEBUI_DIR = ROOT / "FG" / "05_webui"
sys.path.insert(0, str(WEBUI_DIR))

from services.section4_web_verification import (  # noqa: E402
    TriggerSource,
    build_search_plan,
    detect_section4_trigger,
    detect_tender_intent,
)


def test_explicit_english_section_and_sub_clause_trigger():
    result = detect_section4_trigger(
        "Please verify the disclosure required by Section 4(1)(b)(xv)."
    )

    assert result.triggered is True
    assert result.trigger_type == "SECTION_4_1_B"
    assert result.trigger_source == TriggerSource.EXPLICIT_REFERENCE
    assert result.sub_clause == "xv"
    assert result.category == "facilities_for_obtaining_information"


def test_hindi_section_reference_triggers():
    result = detect_section4_trigger("धारा 4(1)(ख) के अंतर्गत सूचना प्रकाशित करें।")

    assert result.triggered is True
    assert result.trigger_source == TriggerSource.EXPLICIT_REFERENCE


def test_proactive_disclosure_phrase_triggers():
    result = detect_section4_trigger("Has the proactive disclosure been published?")

    assert result.triggered is True
    assert result.confidence == 1.0


def test_structured_legal_analysis_can_trigger_without_query_reference():
    result = detect_section4_trigger(
        "Please prepare the PIO response.",
        {
            "point_analysis": [
                {
                    "applicable_provisions": ["2(f)", "4(1)(b)"],
                    "legal_reasoning": "Material disclosure duty.",
                }
            ]
        },
    )

    assert result.triggered is True
    assert result.trigger_source == TriggerSource.LEGAL_ANALYSIS


def test_unstructured_legal_reasoning_does_not_trigger():
    result = detect_section4_trigger(
        "Please prepare the PIO response.",
        {"comment": "Maybe Section 4(1)(b) could be mentioned."},
    )

    assert result.triggered is False


def test_other_rti_sections_do_not_trigger():
    assert detect_section4_trigger("धारा 8 में व्यक्तिगत सूचना का नियम क्या है?").triggered is False
    assert detect_section4_trigger("धारा 7 की समय सीमा क्या है?").triggered is False


def test_generic_tender_query_does_not_enable_section4_search():
    result = detect_section4_trigger("Find the BharatNet tender and contract value.")

    assert result.triggered is False


def test_generic_official_website_query_does_not_imply_section4():
    result = detect_section4_trigger(
        "Where is the employee information published on the official website?"
    )

    assert result.triggered is False
    assert result.tender_intent is False
    assert detect_tender_intent("Find the BharatNet tender.").tender_intent is True


def test_tender_payment_intent_takes_specific_precedence():
    intent = detect_tender_intent(
        "Show monthly payment, deductions and outstanding amount under the contract."
    )

    assert intent.tender_intent is True
    assert intent.intent_type == "PAYMENT_SEARCH"
    assert set(intent.requested_fields) >= {
        "monthly_payments",
        "deductions",
        "outstanding_amount",
    }


def test_ambiguous_classifier_is_strict_and_cannot_trigger_wrong_type():
    calls = []

    def classifier(query, legal_analysis):
        calls.append((query, legal_analysis))
        return {
            "triggered": True,
            "trigger_type": "GENERAL_WEB_SEARCH",
            "confidence": 0.99,
        }

    result = detect_section4_trigger(
        "Under RTI, should this be on a website?",
        semantic_classifier=classifier,
    )

    assert calls
    assert result.triggered is False


def test_ambiguous_classifier_can_recommend_only_section4_route():
    result = detect_section4_trigger(
        "Under RTI, should this be on a website?",
        semantic_classifier=lambda _query, _analysis: {
            "triggered": True,
            "trigger_type": "SECTION_4_1_B",
            "sub_clause": "xiv",
            "confidence": 0.91,
        },
    )

    assert result.triggered is True
    assert result.trigger_source == TriggerSource.SEMANTIC_CLASSIFIER
    assert result.sub_clause == "xiv"


def test_search_plan_extracts_acceptance_example_without_domains():
    query = (
        "Section 4(1)(b): CHiPS द्वारा Tata Projects Limited को BharatNet "
        "Phase-II के लिए मासिक और ब्लॉक-वार भुगतान, कटौती तथा बकाया राशि।"
    )
    trigger = detect_section4_trigger(query)
    plan = build_search_plan(
        query,
        {
            "public_authority": "CHiPS",
            "period": {"from": "2024-04", "to": "2025-03"},
            "information_points": [
                {
                    "requested_information": query,
                    "record_types_requested": ["payment records", "contract"],
                }
            ],
        },
        trigger,
    )

    assert plan.organisation.name == "Chhattisgarh Infotech Promotion Society"
    assert plan.company.name == "Tata Projects Limited"
    assert plan.project.name == "BharatNet Phase-II"
    assert plan.tender.tender_intent is True
    assert set(plan.requested_fields) >= {
        "monthly_payments",
        "block_wise_payments",
        "deductions",
        "outstanding_amount",
    }
    assert all("http://" not in query and "https://" not in query for query in plan.search_queries)


def test_schema_to_dict_uses_plain_enum_values():
    payload = detect_section4_trigger("proactive disclosure").to_dict()

    assert payload["trigger_source"] == "EXPLICIT_REFERENCE"
