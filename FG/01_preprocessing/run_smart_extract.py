"""Smart page-level PDF extraction for RTI/CIC documents.

This entry point avoids OCR for pages that already contain reliable selectable
text. Only pages below the direct-text confidence threshold are rendered and
sent through the existing Stage 1 / Stage 2 page-level hooks.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import fitz
import pdfplumber

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from page_classifier import PageResult, classify_page
from processing_manifest import (
    find_entry,
    load_manifest,
    make_base_entry,
    save_manifest,
    sha256_file,
    upsert_entry,
)


DEFAULT_INPUT = SCRIPT_DIR / "input_pdfs"
DEFAULT_OUTPUT = SCRIPT_DIR / "stage2_output"
logger = logging.getLogger(__name__)


def collect_pdfs(path: Path) -> list[Path]:
    """Collect PDFs from a single file or a directory, sorted for repeatability."""
    if path.is_file() and path.suffix.lower() == ".pdf":
        return [path]
    if path.is_dir():
        return sorted(path.glob("*.pdf"))
    return []


def is_smart_processed(entry: dict[str, Any] | None, output_root: Path, pdf_stem: str) -> bool:
    """Return True when the manifest and structured outputs show completed work."""
    if not entry:
        return False
    if entry.get("stage2_status") not in {"success", "completed_smart"}:
        return False
    md_path = Path(entry.get("stage2_structured_md") or output_root / pdf_stem / "structured.md")
    json_path = Path(entry.get("stage2_structured_json") or output_root / pdf_stem / "structured.json")
    return md_path.exists() and json_path.exists()


def extract_text_with_fallback(pdf_path: Path, page_index: int, plumber_page: Any) -> str:
    """Extract direct text with pdfplumber first, then PyMuPDF if needed."""
    try:
        text = plumber_page.extract_text() or ""
        if text.strip():
            return text
    except Exception as exc:
        logger.warning("%s page %s: pdfplumber failed: %s", pdf_path.name, page_index + 1, exc)

    try:
        with fitz.open(str(pdf_path)) as doc:
            return doc[page_index].get_text("text") or ""
    except Exception as exc:
        logger.warning("%s page %s: PyMuPDF text fallback failed: %s", pdf_path.name, page_index + 1, exc)
        return ""


def extract_critical_fields(text: str) -> dict[str, list[str]]:
    """Extract simple legal/RAG fields from final merged text."""
    return {
        "case_numbers": sorted(set(re.findall(r"\bCIC[ /A-Z0-9_-]{8,}\d{3,}\b", text, flags=re.IGNORECASE))),
        "dates": sorted(set(re.findall(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", text))),
        "sections": sorted(set(re.findall(r"\bSection\s+\d+(?:\(\d+\))?(?:\([a-z]\))?", text, flags=re.IGNORECASE))),
        "emails": sorted(set(re.findall(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, flags=re.IGNORECASE))),
    }


def summarize_methods(page_results: list[PageResult]) -> dict[str, int]:
    """Count extraction methods for reports and manifest summary fields."""
    summary = {"direct_text": 0, "ocr": 0, "hybrid": 0, "failed": 0}
    for page in page_results:
        method = page["extraction_method"]
        summary[method] = summary.get(method, 0) + 1
    return summary


def build_quality_flags(page_results: list[PageResult], warnings: list[str], threshold: float) -> list[str]:
    """Create document-level quality flags from page-level decisions."""
    flags = list(warnings)
    low_pages = [
        page["page_num"]
        for page in page_results
        if page["direct_text_confidence"] < threshold
    ]
    if low_pages:
        flags.append(f"low_confidence_pages: {low_pages}")

    method_summary = summarize_methods(page_results)
    if method_summary.get("ocr", 0) + method_summary.get("hybrid", 0) > len(page_results) / 2:
        flags.append("ocr_used_on_majority_pages")
    if method_summary.get("failed", 0):
        flags.append(f"failed_pages: {method_summary['failed']}")
    return flags


def overall_confidence(page_results: list[PageResult]) -> float:
    """Mean direct-text confidence across pages."""
    if not page_results:
        return 0.0
    return round(
        sum(page["direct_text_confidence"] for page in page_results) / len(page_results),
        4,
    )


def write_outputs(
    pdf_path: Path,
    page_results: list[PageResult],
    output_root: Path,
    started_at: float,
    warnings: list[str],
    threshold: float,
) -> dict[str, Any]:
    """Write structured.md/json, extraction report, and page debug files."""
    doc_dir = output_root / pdf_path.stem
    debug_dir = doc_dir / "page_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    md_parts: list[str] = []
    total_text_chars = 0
    for page in page_results:
        final_text = page["final_text"]
        total_text_chars += len(final_text)
        md_parts.append(f"<!-- Page {page['page_num']} -->")
        md_parts.append(
            f"<!-- extraction_method: {page['extraction_method']} | "
            f"confidence: {page['direct_text_confidence']:.2f} -->"
        )
        md_parts.append(final_text)
        md_parts.append("")
        (debug_dir / f"page_{page['page_num']:03d}.txt").write_text(final_text, encoding="utf-8")

    structured_md = doc_dir / "structured.md"
    structured_md.write_text("\n".join(md_parts).rstrip() + "\n", encoding="utf-8")

    merged_text = "\n\n".join(page["final_text"] for page in page_results)
    confidence = overall_confidence(page_results)
    quality_flags = build_quality_flags(page_results, warnings, threshold)
    payload = {
        "source_pdf": pdf_path.name,
        "total_pages": len(page_results),
        "total_text_chars": total_text_chars,
        "overall_confidence": confidence,
        "pages": page_results,
        "critical_fields": extract_critical_fields(merged_text),
        "quality_flags": quality_flags,
    }

    structured_json = doc_dir / "structured.json"
    structured_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    method_summary = summarize_methods(page_results)
    report = {
        "pdf_name": pdf_path.name,
        "total_pages": len(page_results),
        "direct_text_pages": method_summary.get("direct_text", 0),
        "ocr_pages": method_summary.get("ocr", 0),
        "hybrid_pages": method_summary.get("hybrid", 0),
        "failed_pages": method_summary.get("failed", 0),
        "overall_confidence": confidence,
        "processing_time_seconds": round(time.perf_counter() - started_at, 2),
        "warnings": warnings,
    }

    report_path = doc_dir / "extraction_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "doc_dir": doc_dir,
        "structured_md": structured_md,
        "structured_json": structured_json,
        "report": report,
        "quality_flags": quality_flags,
    }


def process_pdf(
    pdf_path: Path,
    output_root: Path,
    threshold: float,
    force: bool,
    dry_run: bool,
    ocr_only: bool,
    direct_text_only: bool,
) -> tuple[list[PageResult], dict[str, Any] | None]:
    """Process or preview one PDF with page-level routing."""
    started_at = time.perf_counter()
    doc_dir = output_root / pdf_path.stem
    warnings: list[str] = []
    page_results: list[PageResult] = []

    if force and not dry_run and doc_dir.exists():
        shutil.rmtree(doc_dir)

    image_prep = None
    ocr_pipeline = None
    postprocess_page_text = None

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            total_pages = len(pdf.pages)
            for index, page in enumerate(pdf.pages):
                page_num = index + 1
                try:
                    direct_text = extract_text_with_fallback(pdf_path, index, page)
                    result = classify_page(page_num, direct_text, threshold)

                    if ocr_only:
                        result["needs_ocr"] = True
                        result["extraction_method"] = "ocr"
                        result["reason"] = "ocr_only forced by CLI"

                    if direct_text_only:
                        result["needs_ocr"] = False
                        result["final_text"] = direct_text
                        result["extraction_method"] = "direct_text"
                        if not direct_text.strip():
                            warnings.append(f"direct_text_only forced on empty page {page_num}")
                    elif dry_run:
                        if result["needs_ocr"]:
                            result["final_text"] = direct_text
                    elif result["needs_ocr"]:
                        if image_prep is None or ocr_pipeline is None or postprocess_page_text is None:
                            from stage1_image_prep import ImagePrepPipeline
                            from stage2_ocr import OCRPipeline
                            from stage2_ocr.postprocess import postprocess_page_text as _postprocess_page_text

                            image_prep = ImagePrepPipeline(output_dir=doc_dir / "ocr_pages")
                            ocr_pipeline = OCRPipeline(output_dir=output_root)
                            postprocess_page_text = _postprocess_page_text
                        page_output_dir = doc_dir / "ocr_pages"
                        stage1_page = image_prep.process_single_page(pdf_path, index, page_output_dir)
                        ocr_page = ocr_pipeline.process_single_image(Path(stage1_page.image_path), index)
                        ocr_text = postprocess_page_text(ocr_page.raw_text)
                        result["ocr_text"] = ocr_text
                        result["final_text"] = ocr_text
                        result["extraction_method"] = "hybrid" if direct_text.strip() else "ocr"
                    else:
                        result["final_text"] = direct_text

                except Exception as exc:
                    warnings.append(f"page {page_num} failed: {type(exc).__name__}: {exc}")
                    result = PageResult(
                        page_num=page_num,
                        page_type="low_confidence",
                        direct_text="",
                        direct_text_confidence=0.0,
                        needs_ocr=False,
                        ocr_text="",
                        final_text="",
                        extraction_method="failed",
                        legal_markers_found=[],
                        char_count=0,
                        word_count=0,
                        reason=f"page extraction failed: {type(exc).__name__}",
                    )

                page_results.append(result)
                logger.info(
                    "%s page %s/%s: method=%s confidence=%.2f reason=%s",
                    pdf_path.stem,
                    page_num,
                    total_pages,
                    result["extraction_method"],
                    result["direct_text_confidence"],
                    result["reason"],
                )
    except Exception as exc:
        raise RuntimeError(f"could not open PDF: {exc}") from exc

    if dry_run:
        method_summary = summarize_methods(page_results)
        logger.info(
            "[DRY-RUN] %s: direct_text=%s ocr=%s hybrid=%s failed=%s overall_confidence=%.2f",
            pdf_path.name,
            method_summary.get("direct_text", 0),
            method_summary.get("ocr", 0),
            method_summary.get("hybrid", 0),
            method_summary.get("failed", 0),
            overall_confidence(page_results),
        )
        return page_results, None

    output_info = write_outputs(pdf_path, page_results, output_root, started_at, warnings, threshold)
    return page_results, output_info


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart page-level PDF extraction")
    parser.add_argument("input", nargs="?", default=str(DEFAULT_INPUT), help="PDF file or folder containing PDFs")
    parser.add_argument("--output", "-o", default=str(DEFAULT_OUTPUT), help="Stage 2 output directory")
    parser.add_argument("--text-confidence-threshold", type=float, default=0.60, help="Direct text confidence threshold")
    parser.add_argument("--force", action="store_true", help="Reprocess PDFs even when already processed")
    parser.add_argument("--dry-run", action="store_true", help="Classify pages and print actions without writing files")
    parser.add_argument("--limit", type=int, help="Process only the first N eligible PDFs")
    parser.add_argument("--ocr-only", action="store_true", help="Force every page through OCR")
    parser.add_argument("--direct-text-only", action="store_true", help="Never invoke OCR, even for low-confidence pages")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.ocr_only and args.direct_text_only:
        parser.error("--ocr-only and --direct-text-only cannot be used together")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )

    input_path = Path(args.input)
    output_root = Path(args.output)
    pdfs = collect_pdfs(input_path)
    if not pdfs:
        logger.error("No PDF files found at %s", input_path)
        sys.exit(1)

    if args.dry_run:
        logger.info("[DRY-RUN] No files will be written.")
    else:
        output_root.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest()
    processed_count = 0

    for pdf_path in pdfs:
        entry = find_entry(manifest, pdf_stem=pdf_path.stem)
        if is_smart_processed(entry, output_root, pdf_path.stem) and not args.force:
            logger.info("[SKIP] Smart extraction already processed: %s", pdf_path.name)
            continue

        if args.limit is not None and processed_count >= args.limit:
            logger.info("[LIMIT] Smart extraction limit reached (%s); stopping.", args.limit)
            break

        pdf_hash = sha256_file(pdf_path)
        entry = find_entry(manifest, sha256=pdf_hash, pdf_stem=pdf_path.stem) or make_base_entry(pdf_path, pdf_hash)

        logger.info(
            "%s Smart extraction: %s",
            "[FORCE]" if args.force else "[PROCESS]",
            pdf_path.name,
        )

        try:
            page_results, output_info = process_pdf(
                pdf_path=pdf_path,
                output_root=output_root,
                threshold=args.text_confidence_threshold,
                force=args.force,
                dry_run=args.dry_run,
                ocr_only=args.ocr_only,
                direct_text_only=args.direct_text_only,
            )
            processed_count += 1

            if args.dry_run:
                continue

            assert output_info is not None
            method_summary = summarize_methods(page_results)
            entry.update({
                "pdf_name": pdf_path.name,
                "pdf_stem": pdf_path.stem,
                "source_path": str(pdf_path),
                "file_size": pdf_path.stat().st_size,
                "sha256": pdf_hash,
                "stage1_status": "completed_smart",
                "stage2_status": "completed_smart",
                "stage1_output_dir": "",
                "stage2_structured_md": str(output_info["structured_md"]),
                "stage2_structured_json": str(output_info["structured_json"]),
                "overall_confidence": overall_confidence(page_results),
                "extraction_method_summary": method_summary,
                "error": None,
            })
            upsert_entry(manifest, entry)
            save_manifest(manifest)
            logger.info(
                "Done: %s | direct_text=%s ocr=%s hybrid=%s failed=%s",
                pdf_path.name,
                method_summary.get("direct_text", 0),
                method_summary.get("ocr", 0),
                method_summary.get("hybrid", 0),
                method_summary.get("failed", 0),
            )
        except Exception as exc:
            logger.error("[ERROR] Smart extraction failed: %s: %s", pdf_path.name, exc)
            if not args.dry_run:
                entry.update({
                    "stage1_status": "failed",
                    "stage2_status": "failed",
                    "error": str(exc),
                })
                upsert_entry(manifest, entry)
                save_manifest(manifest)

    if args.dry_run:
        logger.info("[DRY-RUN] Smart extraction check complete.")


if __name__ == "__main__":
    main()
