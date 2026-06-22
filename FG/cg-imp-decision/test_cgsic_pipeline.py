import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

SPEC = importlib.util.spec_from_file_location(
    "cgsic_pipeline",
    ROOT / "cgsic_pipeline.py",
)
PIPELINE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PIPELINE)


def test_manifest_has_136_decisions_and_complete_body_coverage():
    manifest = PIPELINE.build_manifest(persist=False)
    decisions = manifest["decisions"]

    assert len(decisions) == 136
    assert {decision["decision_id"] for decision in decisions} == {
        f"CGSIC_IMPORTANT_{index:03d}" for index in range(1, 137)
    }

    covered_pages = set()
    for decision in decisions:
        covered_pages.update(
            range(
                decision["physical_page_start"],
                decision["physical_page_end"] + 1,
            )
        )

    assert covered_pages == set(
        range(PIPELINE.BODY_PAGE_START, PIPELINE.BODY_PAGE_END + 1)
    )


def test_contents_sequence_anomaly_is_preserved_without_bad_boundaries():
    decisions = PIPELINE.build_manifest(persist=False)["decisions"]
    decision_125 = decisions[124]
    decision_126 = decisions[125]

    assert decision_125["printed_page_start"] == 397
    assert decision_126["printed_page_start"] == 395
    assert decision_126["printed_page_end"] == 396
    assert decision_125["printed_page_end"] == 398


def test_unicode_quality_rejects_legacy_font_text():
    bad = PIPELINE.unicode_quality("NÙkhlx<+ jkT; lwpuk vk;ksx")
    good = PIPELINE.unicode_quality("छत्तीसगढ़ राज्य सूचना आयोग")

    assert bad["accepted"] is False
    assert good["accepted"] is True
    assert good["devanagari_ratio"] > 0.8


def test_chunk_metadata_uses_cgsic_schema():
    metadata = PIPELINE.extract_case_metadata(
        """
        अपील प्रकरण क्रमांक ए/48/2006
        अपीलार्थी श्री शंकर मेढ़े
        विरुद्ध जनसूचना अधिकारी, वाणिज्य उद्योग विभाग
        आदेश दिनांक 31-08-2006
        सूचना का अधिकार अधिनियम की धारा 20(1)
        """
    )

    assert "ए/48/2006" in metadata["appeal_number"]
    assert metadata["decision_date"] == "31-08-2006"
    assert metadata["appellant"] == "श्री शंकर मेढ़े"
    assert "जनसूचना अधिकारी" in metadata["public_authority"]


def test_page_aware_packing_preserves_exact_provenance():
    pages = [
        {"physical_page": 18, "printed_page": 1, "text": "पहला अनुच्छेद।"},
        {"physical_page": 19, "printed_page": 2, "text": "दूसरा अनुच्छेद।"},
    ]

    packed = PIPELINE.pack_page_units(
        PIPELINE.page_aware_units(pages),
        target_words=100,
    )

    assert len(packed) == 1
    assert packed[0]["physical_pages"] == [18, 19]
    assert packed[0]["printed_pages"] == [1, 2]


def test_metadata_handles_merged_ocr_heading_and_spelling_variant():
    metadata = PIPELINE.extract_case_metadata(
        "अपील प्रकरण क्रमांक ए 48 / 2006 रायपुर अपीलार्थी श्री शंकर मेढ़े "
        "विरूद्ध जनसूचना अधिकारी, वाणिज्य उद्योग विभाग आदेश दिनांक 31-08-2006"
    )

    assert metadata["appeal_number"] == "ए 48 / 2006 रायपुर"
    assert metadata["appellant"] == "श्री शंकर मेढ़े"
    assert metadata["public_authority"] == "जनसूचना अधिकारी, वाणिज्य उद्योग विभाग"


def test_cached_embedding_model_is_resolved_without_network():
    model = PIPELINE.resolve_embedding_model()

    assert model == "BAAI/bge-m3" or Path(model).exists()
