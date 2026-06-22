import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "cgsic_decision_chunker",
    ROOT / "cgsic_decision_chunker.py",
)
CHUNKER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = CHUNKER
SPEC.loader.exec_module(CHUNKER)


def test_reasoning_requires_combined_legal_signals():
    narrative_type, _ = CHUNKER.classify_paragraph(
        "अपीलार्थी ने आयोग में द्वितीय अपील प्रस्तुत की।"
    )
    reasoning_type, _ = CHUNKER.classify_paragraph(
        "आयोग ने यह पाया कि अधिनियम की धारा 2 स्पष्ट है, अतः सूचना देय है।"
    )

    assert narrative_type == "CASE_NARRATIVE"
    assert reasoning_type in {"COMMISSION_FINDINGS", "LEGAL_REASONING"}


def test_split_validator_marks_multiple_cases_suspect():
    text = (
        "अपील प्रकरण क्रमांक ए/1/2020 अपीलार्थी राम विरुद्ध विभाग "
        "आदेश दिनांक 01-01-2020 सही/- राज्य सूचना आयुक्त "
        "सूचना प्रदान करने के आदेश दिए गए।\n"
        "अपील प्रकरण क्रमांक ए/2/2020 अपीलार्थी श्याम विरुद्ध विभाग "
        "आदेश दिनांक 02-01-2020 सही/- राज्य सूचना आयुक्त"
    )

    report = CHUNKER.validate_split_boundary(text, page_count=2)

    assert report["split_quality"] == "suspect"
    assert report["signals"]["appeal_number_count"] == 2
    assert report["signals"]["order_date_count"] == 2


def test_boundary_validator_ignores_appeal_citation_inside_body():
    text = (
        "अपील प्रकरण क्रमांक ए/1/2020 अपीलार्थी राम विरुद्ध विभाग "
        "आदेश दिनांक 01-01-2020\n"
        "पूर्व अपील प्रकरण क्रमांक ए/934/2012 का उल्लेख किया गया।\n"
        "सूचना प्रदान करने के आदेश दिए गए। सही/- राज्य सूचना आयुक्त"
    )

    report = CHUNKER.validate_split_boundary(text, page_count=1)

    assert report["signals"]["appeal_number_count"] == 1


def test_case_number_supports_second_appeal_and_hindi_prefix():
    appeal = CHUNKER.extract_metadata(
        "द्वितीय अपील प्रकरण क्रमांक ए/2363/2018 अपीलार्थी राम विरुद्ध विभाग"
    )
    complaint = CHUNKER.extract_metadata(
        "शिकायत प्रकरण क्रमांक बी 1170 / 2020 शिकायतकर्ता राम विरुद्ध विभाग"
    )

    assert appeal.appeal_number == "ए/2363/2018"
    assert complaint.appeal_number == "बी 1170 / 2020"


def test_page_fallback_uses_physical_page_when_printed_page_missing():
    fields = CHUNKER.safe_page_fields(
        {
            "decision_page_numbers": [1],
            "physical_page_numbers": [18],
            "printed_page_numbers": [],
        }
    )

    assert fields["page_number"] == 18
    assert fields["printed_page_start"] is None
    assert fields["printed_page_end"] is None


def test_precedent_card_has_required_fields():
    metadata = CHUNKER.DecisionMetadata(rti_sections=["धारा 7"])
    chunks = [
        {
            "chunk_type": "INFORMATION_REQUESTED",
            "text": "आवेदक ने प्रमाणित अभिलेखों की सूचना मांगी।",
        },
        {
            "chunk_type": "COMMISSION_FINDINGS",
            "text": "आयोग ने पाया कि सूचना उपलब्ध कराई जानी चाहिए।",
        },
        {
            "chunk_type": "FINAL_DIRECTION",
            "text": "जनसूचना अधिकारी को सूचना प्रदान करने का निर्देश दिया गया।",
        },
    ]

    card = CHUNKER.build_precedent_card(metadata, chunks)

    assert set(card) == {"issue", "section", "finding", "outcome", "pio_learning"}
    assert card["section"] == ["धारा 7"]
