import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "FG" / "03_chunking"))

from legal_section_chunker import LegalSectionChunker, RETRIEVAL_PRIORITY


GOLDEN_MD = ROOT / "FG" / "01_preprocessing" / "stage2_output" / "CIC_AAOIN_A_2017_102333" / "structured.md"


def chunks_by_type(chunks):
    return {chunk["chunk_type"]: chunk for chunk in chunks}


def test_golden_cic_file_generates_required_legal_chunks():
    chunks = LegalSectionChunker().chunk_file(GOLDEN_MD)
    by_type = chunks_by_type(chunks)

    expected = {
        "CASE_METADATA",
        "INFORMATION_REQUESTED",
        "GROUNDS_FOR_APPEAL",
        "HEARING_SUBMISSIONS",
        "COMMISSION_OBSERVATIONS",
        "FINAL_ORDER",
        "PIO_LEARNING_SIGNAL",
        "PRECEDENT_SUMMARY",
    }
    assert expected.issubset(by_type)


def test_golden_metadata_is_preserved_on_every_chunk():
    chunks = LegalSectionChunker().chunk_file(GOLDEN_MD)

    for chunk in chunks:
        assert chunk["case_number"] == "CIC/AAOIN/A/2017/102333"
        assert chunk["source_type"] == "CIC_DECISION"
        assert chunk["appellant"] == "Sudesh Raghunath Gaikwad"
        assert "Airport Authority of India" in chunk["public_authority"]
        assert chunk["commissioner"] == "Amitava Bhattacharyya"
        assert chunk["hearing_date"] == "05.04.2018"
        assert chunk["chunk_type"]
        assert isinstance(chunk["retrieval_priority"], int)


def test_golden_chunks_contain_expected_legal_content():
    by_type = chunks_by_type(LegalSectionChunker().chunk_file(GOLDEN_MD))

    assert "High Court" in by_type["INFORMATION_REQUESTED"]["text"]
    assert "Committee" in by_type["INFORMATION_REQUESTED"]["text"]
    assert "final report" in by_type["INFORMATION_REQUESTED"]["text"]
    assert "CPIO did not provide" in by_type["GROUNDS_FOR_APPEAL"]["text"]
    assert "20.04.2016" in by_type["HEARING_SUBMISSIONS"]["text"]
    assert "08.05.16" in by_type["HEARING_SUBMISSIONS"]["text"]
    assert "just, proper and pointwise" in by_type["COMMISSION_OBSERVATIONS"]["text"]
    assert "interference of the Commission is not called for" in by_type["COMMISSION_OBSERVATIONS"]["text"]
    assert "appeal is disposed" in by_type["FINAL_ORDER"]["text"]
    assert "Timely, pointwise, and proper replies" in by_type["PIO_LEARNING_SIGNAL"]["text"]


def test_retrieval_priority_ordering_prefers_reasoning_chunks():
    assert RETRIEVAL_PRIORITY["PRECEDENT_SUMMARY"] > RETRIEVAL_PRIORITY["INFORMATION_REQUESTED"]
    assert RETRIEVAL_PRIORITY["COMMISSION_OBSERVATIONS"] > RETRIEVAL_PRIORITY["GROUNDS_FOR_APPEAL"]
    assert RETRIEVAL_PRIORITY["FINAL_ORDER"] > RETRIEVAL_PRIORITY["CASE_METADATA"]


def test_chunk_directory_inputs_stage2_output_folders(tmp_path):
    # Create a fake stage2_output folder with a structured.md file.
    doc_dir = tmp_path / "CIC_AAOIN_A_2017_102333"
    doc_dir.mkdir(parents=True)
    structured_md = doc_dir / "structured.md"
    structured_md.write_text("# Facts\nThis is a fact section.\n# Order\nAppeal is disposed.", encoding="utf-8")

    output_dir = tmp_path / "legal_output"
    chunks = LegalSectionChunker().chunk_file(tmp_path, output_dir)

    assert chunks
    assert all(chunk["source"] == "CIC_AAOIN_A_2017_102333" for chunk in chunks)
    assert (output_dir / "CIC_AAOIN_A_2017_102333" / "legal_chunks.jsonl").exists()
