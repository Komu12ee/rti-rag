#!/usr/bin/env python3
"""CGSIC important-decisions ingestion pipeline.

This module reuses Project B's existing Stage 1 and Stage 2 OCR components,
then adds compilation-aware decision splitting, CGSIC legal chunking, and
indexing into a dedicated Qdrant collection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import fitz

from config import (
    ARTIFACTS_DIR,
    BODY_PAGE_END,
    BODY_PAGE_START,
    CHUNKS_DIR,
    CHUNKS_PATH,
    COLLECTION_NAME,
    COMMISSION,
    CORPUS,
    DECISION_PDF_DIR,
    DECISION_TEXT_DIR,
    INDEX_MANIFEST_PATH,
    JURISDICTION,
    MANIFEST_PATH,
    PAGE_TEXT_DIR,
    PDF_PATH,
    PHYSICAL_PAGE_COUNT,
    PRINTED_PAGE_OFFSET,
    PRINTED_START_PAGES,
    SOURCE_DOCUMENT_ID,
    SOURCE_TYPE,
    VECTOR_SIZE,
    WORK_DIR,
)


LOGGER = logging.getLogger("cgsic_pipeline")

FG_ROOT = Path(__file__).resolve().parents[1]
PREPROCESSING_DIR = FG_ROOT / "01_preprocessing"
if str(PREPROCESSING_DIR) not in sys.path:
    sys.path.insert(0, str(PREPROCESSING_DIR))


RETRIEVAL_PRIORITY = {
    "LEGAL_REASONING": 100,
    "COMMISSION_FINDINGS": 98,
    "FINAL_DIRECTION": 95,
    "PENALTY_OR_SHOW_CAUSE": 92,
    "PRECEDENT_SUMMARY": 90,
    "CITED_PROVISION": 85,
    "INFORMATION_REQUESTED": 75,
    "CPIO_RESPONSE": 70,
    "FIRST_APPEAL_HISTORY": 65,
    "CASE_NARRATIVE": 55,
    "CASE_METADATA": 40,
}

SECTION_MARKERS = {
    "INFORMATION_REQUESTED": (
        "जानकारी चाही",
        "सूचना चाही",
        "आवेदन प्रस्तुत",
        "सूचना आवेदन",
        "मांगी गई जानकारी",
    ),
    "CPIO_RESPONSE": (
        "जनसूचना अधिकारी",
        "लोक सूचना अधिकारी",
        "जवाब प्रस्तुत",
        "उत्तर दिया",
    ),
    "FIRST_APPEAL_HISTORY": (
        "प्रथम अपील",
        "प्रथम अपीलीय",
    ),
    "COMMISSION_FINDINGS": (
        "आयोग का अभिमत",
        "आयोग के समक्ष",
        "आयोग द्वारा अवलोकन",
        "आयोग यह पाता",
        "आयोग का मत",
    ),
    "FINAL_DIRECTION": (
        "निर्देशित किया जाता",
        "आदेशित किया जाता",
        "अपील निराकृत",
        "प्रकरण समाप्त",
        "अपील समाप्त",
        "आदेश पारित",
    ),
    "PENALTY_OR_SHOW_CAUSE": (
        "कारण बताओ",
        "शास्ति",
        "जुर्माना",
        "धारा 20",
        "धारा २०",
    ),
}


def ensure_directories() -> None:
    for path in (
        ARTIFACTS_DIR,
        WORK_DIR,
        PAGE_TEXT_DIR,
        DECISION_PDF_DIR,
        DECISION_TEXT_DIR,
        CHUNKS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_manifest(
    pdf_path: Path = PDF_PATH,
    persist: bool = True,
) -> dict[str, Any]:
    """Build the 136-decision manifest from verified contents-table pages."""
    if len(PRINTED_START_PAGES) != 136:
        raise ValueError("Expected exactly 136 contents-table entries")
    if len(set(PRINTED_START_PAGES)) != 136:
        raise ValueError("Contents-table start pages must be unique")

    document = fitz.open(pdf_path)
    if document.page_count != PHYSICAL_PAGE_COUNT:
        raise ValueError(
            f"Expected {PHYSICAL_PAGE_COUNT} PDF pages, found {document.page_count}"
        )

    sorted_starts = sorted(PRINTED_START_PAGES)
    next_start = {
        start: (
            sorted_starts[index + 1]
            if index + 1 < len(sorted_starts)
            else BODY_PAGE_END - PRINTED_PAGE_OFFSET + 1
        )
        for index, start in enumerate(sorted_starts)
    }

    decisions = []
    for sequence, printed_start in enumerate(PRINTED_START_PAGES, 1):
        printed_end = next_start[printed_start] - 1
        physical_start = printed_start + PRINTED_PAGE_OFFSET
        physical_end = min(printed_end + PRINTED_PAGE_OFFSET, BODY_PAGE_END)
        decisions.append(
            {
                "sequence_in_contents": sequence,
                "decision_id": f"CGSIC_IMPORTANT_{sequence:03d}",
                "source_document_id": SOURCE_DOCUMENT_ID,
                "source_file": pdf_path.name,
                "source_type": "CGSIC_IMPORTANT_DECISION",
                "corpus": CORPUS,
                "commission": COMMISSION,
                "jurisdiction": JURISDICTION,
                "printed_page_start": printed_start,
                "printed_page_end": printed_end,
                "physical_page_start": physical_start,
                "physical_page_end": physical_end,
                "page_count": physical_end - physical_start + 1,
                "toc_order_matches_page_order": sequence
                == sorted_starts.index(printed_start) + 1,
                "ocr_status": "pending",
                "chunk_status": "pending",
                "index_status": "pending",
            }
        )

    manifest = {
        "schema_version": 1,
        "document": {
            "document_id": SOURCE_DOCUMENT_ID,
            "source_file": pdf_path.name,
            "source_path": str(pdf_path),
            "sha256": sha256_file(pdf_path),
            "source_type": SOURCE_TYPE,
            "corpus": CORPUS,
            "commission": COMMISSION,
            "jurisdiction": JURISDICTION,
            "physical_pages": document.page_count,
            "decision_count_expected": 136,
            "body_page_start": BODY_PAGE_START,
            "body_page_end": BODY_PAGE_END,
            "printed_page_offset": PRINTED_PAGE_OFFSET,
            "unicode_extraction_policy": "forced_project_b_ocr",
        },
        "decisions": decisions,
    }
    if persist:
        write_json(MANIFEST_PATH, manifest)
        LOGGER.info("Wrote 136-decision manifest: %s", MANIFEST_PATH)
    return manifest


def split_decision_pdfs(pdf_path: Path = PDF_PATH) -> None:
    """Split the compilation into one page-accurate PDF per decision."""
    manifest = read_json(MANIFEST_PATH) if MANIFEST_PATH.exists() else build_manifest(pdf_path)
    source = fitz.open(pdf_path)

    for decision in manifest["decisions"]:
        output_path = DECISION_PDF_DIR / f"{decision['decision_id']}.pdf"
        if output_path.exists():
            continue
        target = fitz.open()
        target.insert_pdf(
            source,
            from_page=decision["physical_page_start"] - 1,
            to_page=decision["physical_page_end"] - 1,
        )
        target.set_metadata(
            {
                "title": decision["decision_id"],
                "subject": (
                    f"CGSIC important decision; source pages "
                    f"{decision['physical_page_start']}-{decision['physical_page_end']}"
                ),
            }
        )
        target.save(output_path, garbage=4, deflate=True)
        target.close()
    LOGGER.info("Decision PDFs available in %s", DECISION_PDF_DIR)


def _page_artifact_path(physical_page: int) -> Path:
    return PAGE_TEXT_DIR / f"page_{physical_page:03d}.json"


def extract_unicode_pages(
    pdf_path: Path = PDF_PATH,
    start_page: int = BODY_PAGE_START,
    end_page: int = BODY_PAGE_END,
    force: bool = False,
    keep_images: bool = False,
) -> None:
    """Force OCR through Project B's existing Stage 1/Stage 2 components.

    A JSON checkpoint is written after each page, making the long CPU workflow
    safely resumable.
    """
    from stage1_image_prep import ImagePrepPipeline
    from stage2_ocr import OCRPipeline
    from stage2_ocr.postprocess import postprocess_page_text

    if start_page < 1 or end_page > PHYSICAL_PAGE_COUNT or start_page > end_page:
        raise ValueError("Invalid OCR page range")

    render_dir = WORK_DIR / "ocr_pages"
    render_dir.mkdir(parents=True, exist_ok=True)
    image_prep = ImagePrepPipeline(
        output_dir=render_dir,
        mask_stamps_in_output=False,
        save_debug_images=False,
    )
    ocr_pipeline = OCRPipeline(output_dir=ARTIFACTS_DIR)

    source = fitz.open(pdf_path)
    for physical_page in range(start_page, end_page + 1):
        output_path = _page_artifact_path(physical_page)
        if output_path.exists() and not force:
            LOGGER.info("[SKIP] OCR page %s", physical_page)
            continue

        page_index = physical_page - 1
        selectable_text = source[page_index].get_text("text") or ""
        stage1_page = image_prep.process_single_page(
            pdf_path,
            page_index,
            render_dir,
        )
        page_result = ocr_pipeline.process_single_image(
            Path(stage1_page.image_path),
            page_index,
        )
        unicode_text = postprocess_page_text(page_result.raw_text)
        payload = {
            "source_file": pdf_path.name,
            "source_document_id": SOURCE_DOCUMENT_ID,
            "physical_page": physical_page,
            "printed_page": (
                physical_page - PRINTED_PAGE_OFFSET
                if BODY_PAGE_START <= physical_page <= BODY_PAGE_END
                else None
            ),
            "extraction_method": "project_b_forced_ocr",
            "ocr_engine": "docling_easyocr",
            "ocr_languages": ["hi", "en"],
            "ocr_confidence": page_result.confidence,
            "text": unicode_text,
            "selectable_text_raw": selectable_text,
            "selectable_text_rejected": True,
            "quality": unicode_quality(unicode_text),
            "elements": [element.to_dict() for element in page_result.elements],
        }
        write_json(output_path, payload)
        (PAGE_TEXT_DIR / f"page_{physical_page:03d}.txt").write_text(
            unicode_text + "\n",
            encoding="utf-8",
        )
        LOGGER.info(
            "[OCR] page %s chars=%s devanagari=%.3f",
            physical_page,
            len(unicode_text),
            payload["quality"]["devanagari_ratio"],
        )
        if not keep_images:
            Path(stage1_page.image_path).unlink(missing_ok=True)


def unicode_quality(text: str) -> dict[str, Any]:
    letters = [char for char in text if char.isalpha()]
    devanagari = sum("\u0900" <= char <= "\u097f" for char in text)
    script_characters = sum(
        char.isalpha() or "\u0900" <= char <= "\u097f" for char in text
    )
    devanagari_ratio = devanagari / max(script_characters, 1)
    suspicious = len(re.findall(r"(?:vk;|Ù|<\+|NÙ|jkT;|lwpuk)", text))
    return {
        "characters": len(text),
        "letter_characters": len(letters),
        "devanagari_characters": devanagari,
        "script_characters": script_characters,
        "devanagari_ratio": round(devanagari_ratio, 4),
        "legacy_font_markers": suspicious,
        "accepted": (
            bool(text.strip())
            and suspicious == 0
            and devanagari_ratio >= 0.45
        ),
    }


def assemble_decision_documents() -> None:
    """Create per-decision structured.md/json from page OCR checkpoints."""
    manifest = read_json(MANIFEST_PATH)
    changed = False
    for decision in manifest["decisions"]:
        pages = []
        missing = []
        for physical_page in range(
            decision["physical_page_start"],
            decision["physical_page_end"] + 1,
        ):
            artifact = _page_artifact_path(physical_page)
            if not artifact.exists():
                missing.append(physical_page)
                continue
            pages.append(read_json(artifact))

        decision_dir = DECISION_TEXT_DIR / decision["decision_id"]
        decision_dir.mkdir(parents=True, exist_ok=True)
        if missing:
            decision["ocr_status"] = "partial" if pages else "pending"
            decision["missing_ocr_pages"] = missing
            changed = True
            continue

        md_parts = []
        for page in pages:
            md_parts.extend(
                [
                    f"<!-- Physical Page {page['physical_page']} -->",
                    f"<!-- Printed Page {page['printed_page']} -->",
                    page["text"],
                    "",
                ]
            )
        structured_md = "\n".join(md_parts).rstrip() + "\n"
        (decision_dir / "structured.md").write_text(structured_md, encoding="utf-8")
        write_json(
            decision_dir / "structured.json",
            {
                **decision,
                "source_file": PDF_PATH.name,
                "pages": pages,
                "total_text_chars": sum(len(page["text"]) for page in pages),
            },
        )
        decision["ocr_status"] = "complete"
        decision["structured_md"] = str(decision_dir / "structured.md")
        decision["structured_json"] = str(decision_dir / "structured.json")
        decision.pop("missing_ocr_pages", None)
        changed = True

    if changed:
        write_json(MANIFEST_PATH, manifest)


def normalize_space(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_case_metadata(text: str) -> dict[str, Any]:
    head = text[:5000]
    appeal_match = re.search(
        r"(?:अपील|शिकायत)\s*प्रकरण\s*क्रमांक\s*[:\-]?\s*"
        r"(.+?)(?=\s+(?:अपीलार्थी|अपीलकर्ता|विरुद्ध|विरूद्ध|बनाम)|\n|$)",
        head,
        flags=re.IGNORECASE,
    )
    date_match = re.search(
        r"(?:आदेश|निर्णय)\s*दिनांक\s*[:\-]?\s*"
        r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
        head,
    )
    return {
        "appeal_number": normalize_space(appeal_match.group(1)) if appeal_match else "",
        "decision_date": date_match.group(1) if date_match else "",
        "appellant": extract_between(
            head,
            ("अपीलार्थी", "अपीलकर्ता"),
            ("विरुद्ध", "विरूद्ध", "बनाम"),
        ),
        "public_authority": extract_between(
            head,
            ("विरुद्ध", "विरूद्ध", "बनाम"),
            ("आदेश दिनांक", "निर्णय दिनांक", "निर्णय"),
        ),
        "rti_sections": sorted(
            set(
                match.group(0)
                for match in re.finditer(
                    r"धारा\s*[0-9०-९]+(?:\s*\([^)]+\))*",
                    text,
                )
            )
        ),
    }


def extract_between(text: str, starts: Iterable[str], ends: Iterable[str]) -> str:
    start_match = None
    for marker in starts:
        start_match = re.search(re.escape(marker), text, re.IGNORECASE)
        if start_match:
            break
    if not start_match:
        return ""
    remainder = text[start_match.end() :]
    end_positions = []
    for marker in ends:
        match = re.search(re.escape(marker), remainder, re.IGNORECASE)
        if match:
            end_positions.append(match.start())
    value = remainder[: min(end_positions)] if end_positions else remainder[:500]
    return normalize_space(value).lstrip("# ").strip()[:500]


def paragraph_units(text: str) -> list[str]:
    cleaned = re.sub(r"<!--[^>]+-->", "", text)
    blocks = [
        normalize_space(block)
        for block in re.split(r"\n\s*\n|(?=\n\s*\d+\s*[./)])", cleaned)
        if normalize_space(block)
    ]
    if len(blocks) <= 1:
        blocks = [
            normalize_space(block)
            for block in re.split(r"(?<=[।.!?])\s+", cleaned)
            if normalize_space(block)
        ]
    return blocks


def classify_chunk(text: str, is_first: bool, is_last: bool) -> str:
    lowered = text.lower()
    if is_first:
        return "CASE_METADATA"
    for chunk_type in (
        "PENALTY_OR_SHOW_CAUSE",
        "FINAL_DIRECTION",
        "COMMISSION_FINDINGS",
        "FIRST_APPEAL_HISTORY",
        "CPIO_RESPONSE",
        "INFORMATION_REQUESTED",
    ):
        if any(marker.lower() in lowered for marker in SECTION_MARKERS[chunk_type]):
            return chunk_type
    if re.search(r"धारा\s*[0-9०-९]+", text):
        return "CITED_PROVISION"
    if is_last:
        return "FINAL_DIRECTION"
    if "आयोग" in text or "अधिनियम" in text:
        return "LEGAL_REASONING"
    return "CASE_NARRATIVE"


def pack_units(units: list[str], target_words: int = 350, hard_max_words: int = 600) -> list[str]:
    packed = []
    current: list[str] = []
    for unit in units:
        words = unit.split()
        if len(words) > hard_max_words:
            if current:
                packed.append("\n\n".join(current))
                current = []
            packed.extend(
                " ".join(words[index : index + hard_max_words])
                for index in range(0, len(words), hard_max_words)
            )
            continue
        candidate = sum(len(part.split()) for part in current) + len(words)
        if current and candidate > target_words:
            packed.append("\n\n".join(current))
            current = [unit]
        else:
            current.append(unit)
    if current:
        packed.append("\n\n".join(current))
    return packed


def page_aware_units(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    units = []
    for page in pages:
        for text in paragraph_units(page["text"]):
            units.append(
                {
                    "text": text,
                    "physical_pages": [page["physical_page"]],
                    "printed_pages": [page["printed_page"]],
                }
            )
    return units


def pack_page_units(
    units: list[dict[str, Any]],
    target_words: int = 350,
    hard_max_words: int = 600,
) -> list[dict[str, Any]]:
    packed = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        packed.append(
            {
                "text": "\n\n".join(unit["text"] for unit in current),
                "physical_pages": sorted(
                    {
                        page
                        for unit in current
                        for page in unit["physical_pages"]
                    }
                ),
                "printed_pages": sorted(
                    {
                        page
                        for unit in current
                        for page in unit["printed_pages"]
                        if page is not None
                    }
                ),
            }
        )
        current.clear()

    for unit in units:
        words = unit["text"].split()
        if len(words) > hard_max_words:
            flush()
            for index in range(0, len(words), hard_max_words):
                packed.append(
                    {
                        "text": " ".join(words[index : index + hard_max_words]),
                        "physical_pages": unit["physical_pages"],
                        "printed_pages": unit["printed_pages"],
                    }
                )
            continue

        candidate = sum(len(item["text"].split()) for item in current) + len(words)
        if current and candidate > target_words:
            flush()
        current.append(unit)

    flush()
    return packed


def create_legal_chunks() -> int:
    manifest = read_json(MANIFEST_PATH)
    chunks = []
    for decision in manifest["decisions"]:
        decision_dir = DECISION_TEXT_DIR / decision["decision_id"]
        json_path = decision_dir / "structured.json"
        if not json_path.exists():
            continue
        structured = read_json(json_path)
        full_text = "\n\n".join(page["text"] for page in structured["pages"])
        metadata = extract_case_metadata(full_text)
        packed = pack_page_units(page_aware_units(structured["pages"]))
        decision_chunks = []

        for index, packed_chunk in enumerate(packed, 1):
            text = packed_chunk["text"]
            chunk_type = classify_chunk(
                text,
                is_first=index == 1,
                is_last=index == len(packed),
            )
            physical_pages = packed_chunk["physical_pages"]
            printed_pages = packed_chunk["printed_pages"]
            chunk = {
                "chunk_id": f"{decision['decision_id']}_{chunk_type}_{index:03d}",
                "text": normalize_space(text),
                "source": PDF_PATH.name,
                "actual_pdf": f"{decision['decision_id']}.pdf",
                "decision_pdf": f"{decision['decision_id']}.pdf",
                "source_document_id": SOURCE_DOCUMENT_ID,
                "source_type": "CGSIC_IMPORTANT_DECISION",
                "corpus": CORPUS,
                "commission": COMMISSION,
                "jurisdiction": JURISDICTION,
                "decision_id": decision["decision_id"],
                "sequence_in_compilation": decision["sequence_in_contents"],
                **metadata,
                "chunk_type": chunk_type,
                "page_number": min(printed_pages),
                "physical_page_numbers": physical_pages,
                "physical_page_start": min(physical_pages),
                "physical_page_end": max(physical_pages),
                "printed_page_numbers": printed_pages,
                "printed_page_start": min(printed_pages),
                "printed_page_end": max(printed_pages),
                "retrieval_priority": RETRIEVAL_PRIORITY[chunk_type],
                "language": "hi",
                "is_derived": False,
            }
            decision_chunks.append(chunk)

        if not decision_chunks:
            decision["chunk_status"] = "empty"
            decision["chunk_count"] = 0
            continue

        summary_text = (
            f"प्रकरण: {metadata['appeal_number'] or decision['decision_id']}. "
            f"अपीलार्थी: {metadata['appellant']}. "
            f"लोक प्राधिकारी: {metadata['public_authority']}. "
            f"मुख्य निर्णय अंश: "
            + " ".join(
                chunk["text"][:350]
                for chunk in decision_chunks
                if chunk["chunk_type"]
                in {"COMMISSION_FINDINGS", "FINAL_DIRECTION", "LEGAL_REASONING"}
            )[:1200]
        )
        summary_chunk = {
            **decision_chunks[0],
            "chunk_id": f"{decision['decision_id']}_PRECEDENT_SUMMARY_999",
            "text": normalize_space(summary_text),
            "chunk_type": "PRECEDENT_SUMMARY",
            "retrieval_priority": RETRIEVAL_PRIORITY["PRECEDENT_SUMMARY"],
            "is_derived": True,
        }
        summary_physical_pages = sorted(
            {
                page
                for chunk in decision_chunks
                for page in chunk["physical_page_numbers"]
            }
        )
        summary_printed_pages = sorted(
            {
                page
                for chunk in decision_chunks
                for page in chunk["printed_page_numbers"]
            }
        )
        summary_chunk.update(
            {
                "page_number": min(summary_printed_pages),
                "physical_page_numbers": summary_physical_pages,
                "physical_page_start": min(summary_physical_pages),
                "physical_page_end": max(summary_physical_pages),
                "printed_page_numbers": summary_printed_pages,
                "printed_page_start": min(summary_printed_pages),
                "printed_page_end": max(summary_printed_pages),
            }
        )
        decision_chunks.append(summary_chunk)
        chunks.extend(decision_chunks)
        decision["chunk_status"] = "complete"
        decision["chunk_count"] = len(decision_chunks)

    CHUNKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CHUNKS_PATH.open("w", encoding="utf-8") as stream:
        for chunk in chunks:
            stream.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    write_json(MANIFEST_PATH, manifest)
    LOGGER.info("Wrote %s chunks to %s", len(chunks), CHUNKS_PATH)
    return len(chunks)


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if line:
                yield json.loads(line)


def resolve_embedding_model() -> str:
    configured = os.getenv("CGSIC_EMBEDDING_MODEL")
    if configured:
        return configured

    cache_root = Path(
        os.getenv(
            "HF_HOME",
            Path.home() / ".cache" / "huggingface",
        )
    )
    snapshots = (
        cache_root
        / "hub"
        / "models--BAAI--bge-m3"
        / "snapshots"
    )
    if snapshots.exists():
        cached = sorted(
            path
            for path in snapshots.iterdir()
            if path.is_dir() and (path / "tokenizer_config.json").exists()
        )
        if cached:
            return str(cached[-1])
    return "BAAI/bge-m3"


def index_chunks(
    qdrant_path: Path,
    collection_name: str = COLLECTION_NAME,
    recreate: bool = False,
    batch_size: int = 8,
    allow_partial: bool = False,
) -> int:
    chunks = list(iter_jsonl(CHUNKS_PATH))
    if not chunks:
        raise RuntimeError("No CGSIC chunks are available for indexing")
    manifest = read_json(MANIFEST_PATH)
    complete_decisions = sum(
        decision.get("chunk_status") == "complete"
        for decision in manifest["decisions"]
    )
    if not allow_partial and complete_decisions != len(manifest["decisions"]):
        raise RuntimeError(
            "Refusing to index a partial CGSIC corpus: "
            f"{complete_decisions}/{len(manifest['decisions'])} decisions are ready. "
            "Finish OCR and chunking, or pass --allow-partial for a test index."
        )

    from FlagEmbedding import BGEM3FlagModel
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    qdrant_path.mkdir(parents=True, exist_ok=True)
    client = QdrantClient(path=str(qdrant_path))
    try:
        if recreate and client.collection_exists(collection_name):
            client.delete_collection(collection_name)
        if not client.collection_exists(collection_name):
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )

        embedding_model = resolve_embedding_model()
        LOGGER.info("Loading embedding model from %s", embedding_model)
        model = BGEM3FlagModel(embedding_model, use_fp16=False)
        model.return_sparse = True
        indexed = 0
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            encoded = model.encode(
                [chunk["text"] for chunk in batch],
                batch_size=batch_size,
                max_length=1024,
            )
            dense_vectors = encoded["dense_vecs"]
            sparse_vectors = encoded.get("lexical_weights", [None] * len(batch))
            points = []
            for offset, (chunk, dense, sparse) in enumerate(
                zip(batch, dense_vectors, sparse_vectors)
            ):
                payload = dict(chunk)
                if sparse is not None:
                    payload["sparse_embedding"] = {
                        str(key): float(value) for key, value in sparse.items()
                    }
                points.append(
                    PointStruct(
                        id=start + offset,
                        vector=dense.tolist(),
                        payload=payload,
                    )
                )
            client.upsert(collection_name=collection_name, points=points)
            indexed += len(points)
            LOGGER.info("Indexed %s/%s chunks", indexed, len(chunks))

        write_json(
            INDEX_MANIFEST_PATH,
            {
                "collection": collection_name,
                "qdrant_path": str(qdrant_path),
                "indexed_chunks": indexed,
                "vector_size": VECTOR_SIZE,
                "distance": "Cosine",
                "embedding_model": embedding_model,
                "source_chunks": str(CHUNKS_PATH),
            },
        )
        return indexed
    finally:
        client.close()


def status() -> dict[str, Any]:
    manifest = read_json(MANIFEST_PATH) if MANIFEST_PATH.exists() else None
    page_json = list(PAGE_TEXT_DIR.glob("page_*.json"))
    decision_pdfs = list(DECISION_PDF_DIR.glob("*.pdf"))
    decision_md = list(DECISION_TEXT_DIR.glob("*/structured.md"))
    chunk_count = sum(1 for _ in iter_jsonl(CHUNKS_PATH)) if CHUNKS_PATH.exists() else 0
    result = {
        "manifest_exists": MANIFEST_PATH.exists(),
        "manifest_decisions": len(manifest["decisions"]) if manifest else 0,
        "ocr_decisions_complete": sum(
            decision.get("ocr_status") == "complete"
            for decision in manifest["decisions"]
        )
        if manifest
        else 0,
        "chunk_decisions_complete": sum(
            decision.get("chunk_status") == "complete"
            for decision in manifest["decisions"]
        )
        if manifest
        else 0,
        "ocr_pages_complete": len(page_json),
        "ocr_pages_expected": BODY_PAGE_END - BODY_PAGE_START + 1,
        "decision_pdfs": len(decision_pdfs),
        "decision_structured_md": len(decision_md),
        "chunks": chunk_count,
        "index_manifest_exists": INDEX_MANIFEST_PATH.exists(),
    }
    print(json.dumps(result, indent=2))
    return result


def default_qdrant_path() -> Path:
    return Path(
        os.getenv(
            "CGSIC_QDRANT_PATH",
            FG_ROOT / "04_embeddings_and_kg" / "db" / "qdrant_local_fg",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("manifest")
    subparsers.add_parser("split")

    ocr_parser = subparsers.add_parser("ocr")
    ocr_parser.add_argument("--start-page", type=int, default=BODY_PAGE_START)
    ocr_parser.add_argument("--end-page", type=int, default=BODY_PAGE_END)
    ocr_parser.add_argument("--force", action="store_true")
    ocr_parser.add_argument("--keep-images", action="store_true")

    subparsers.add_parser("assemble")
    subparsers.add_parser("chunk")

    index_parser = subparsers.add_parser("index")
    index_parser.add_argument("--qdrant-path", type=Path, default=default_qdrant_path())
    index_parser.add_argument("--collection", default=COLLECTION_NAME)
    index_parser.add_argument("--recreate", action="store_true")
    index_parser.add_argument("--batch-size", type=int, default=8)
    index_parser.add_argument("--allow-partial", action="store_true")

    subparsers.add_parser("status")

    all_parser = subparsers.add_parser("all")
    all_parser.add_argument("--qdrant-path", type=Path, default=default_qdrant_path())
    all_parser.add_argument("--collection", default=COLLECTION_NAME)
    all_parser.add_argument("--recreate", action="store_true")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
    )
    ensure_directories()

    if args.command == "manifest":
        build_manifest()
    elif args.command == "split":
        if not MANIFEST_PATH.exists():
            build_manifest()
        split_decision_pdfs()
    elif args.command == "ocr":
        extract_unicode_pages(
            start_page=args.start_page,
            end_page=args.end_page,
            force=args.force,
            keep_images=args.keep_images,
        )
    elif args.command == "assemble":
        assemble_decision_documents()
    elif args.command == "chunk":
        assemble_decision_documents()
        create_legal_chunks()
    elif args.command == "index":
        index_chunks(
            args.qdrant_path,
            collection_name=args.collection,
            recreate=args.recreate,
            batch_size=args.batch_size,
            allow_partial=args.allow_partial,
        )
    elif args.command == "status":
        status()
    elif args.command == "all":
        build_manifest()
        split_decision_pdfs()
        extract_unicode_pages()
        assemble_decision_documents()
        create_legal_chunks()
        index_chunks(
            args.qdrant_path,
            collection_name=args.collection,
            recreate=args.recreate,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
