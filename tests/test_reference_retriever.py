import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "FG" / "03_chunking"))

from legal_section_chunker import LegalSectionChunker


GOLDEN_MD = ROOT / "FG" / "01_preprocessing" / "stage2_output" / "CIC_AAOIN_A_2017_102333" / "structured.md"


def make_reference_card_payload(chunk):
    return {
        "rank": 1,
        "source": chunk["source"],
        "actual_pdf": f"{chunk['source']}.pdf",
        "score": 0.99,
        "text": chunk["text"],
        "excerpt": chunk["text"][:250],
        "parent_id": chunk["chunk_id"],
        "chunk_type": chunk["chunk_type"],
        "case_number": chunk["case_number"],
        "public_authority": chunk["public_authority"],
        "outcome": chunk["outcome"],
        "hearing_date": chunk["hearing_date"],
        "retrieval_priority": chunk["retrieval_priority"],
        "precedent_summary": chunk["text"] if chunk["chunk_type"] == "PRECEDENT_SUMMARY" else "",
        "commission_observations": chunk["text"] if chunk["chunk_type"] == "COMMISSION_OBSERVATIONS" else "",
        "pio_learning_signal": chunk["text"] if chunk["chunk_type"] == "PIO_LEARNING_SIGNAL" else "",
    }


def test_reference_card_payload_contains_legal_fields():
    chunks = LegalSectionChunker().chunk_file(GOLDEN_MD)
    observation = next(chunk for chunk in chunks if chunk["chunk_type"] == "COMMISSION_OBSERVATIONS")
    payload = make_reference_card_payload(observation)

    assert payload["chunk_type"] == "COMMISSION_OBSERVATIONS"
    assert payload["case_number"] == "CIC/AAOIN/A/2017/102333"
    assert payload["public_authority"] == "Airport Authority of India"
    assert payload["outcome"] == "appeal disposed of"
    assert payload["hearing_date"] == "05.04.2018"
    assert "just, proper and pointwise" in payload["commission_observations"]


def test_reference_card_payload_surfaces_pio_learning_signal():
    chunks = LegalSectionChunker().chunk_file(GOLDEN_MD)
    learning = next(chunk for chunk in chunks if chunk["chunk_type"] == "PIO_LEARNING_SIGNAL")
    payload = make_reference_card_payload(learning)

    assert payload["chunk_type"] == "PIO_LEARNING_SIGNAL"
    assert "Timely, pointwise, and proper replies" in payload["pio_learning_signal"]
