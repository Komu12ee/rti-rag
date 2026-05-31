"""Stage 2 orchestration pipeline.

Takes Stage 1 output (cleaned images + metadata) and runs Docling OCR on
each page. Produces structured document output with headings, paragraphs,
tables, and lists properly identified.

Reads from: stage1_output/<doc_name>/page_XXXX.png + metadata.json
Writes to:  stage2_output/<doc_name>/structured.json + structured.md
"""

import gc
import math
import json
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from dotenv import load_dotenv
import fitz

from .config import (
    DEFAULT_OUTPUT_DIR,
    OUTPUT_FORMATS,
    PAGE_CONFIDENCE_THRESHOLD,
    SARVAM_OCR_THRESHOLD,
)
from .docling_ocr import create_converter, process_image
from .models import DocumentOCRResult, PageOCRResult, DocumentElement, ElementType
from .postprocess import postprocess_page_text, extract_critical_fields

logger = logging.getLogger(__name__)
load_dotenv()


def _low_confidence_pages(
    page_confidences: dict[int, float | None],
    threshold: float,
) -> list[int]:
    return sorted(
        page_no
        for page_no, score in page_confidences.items()
        if score is None or score < threshold
    )


def _source_map_from_confidences(
    page_confidences: dict[int, float | None],
    low_pages: list[int],
) -> dict[int, str]:
    low_set = set(low_pages)
    return {
        page_no: ("sarvam" if page_no in low_set else "docling")
        for page_no in sorted(page_confidences.keys())
    }


class OCRPipeline:
    """Stage 2 pipeline: OCR and structure extraction.

    Usage
    -----
    >>> pipeline = OCRPipeline()
    >>> result = pipeline.process("stage1_output/letter 376 date 18-6-24 agenda letter")
    >>> print(result.to_markdown())
    """

    def __init__(self, output_dir: str | Path = DEFAULT_OUTPUT_DIR):
        self.output_dir = Path(output_dir)
        self._converter = None

    def _get_converter(self):
        """Lazy-load the Docling converter (models loaded once)."""
        if self._converter is None:
            self._converter = create_converter()
        return self._converter

    def process(self, stage1_dir: str | Path) -> DocumentOCRResult:
        """Run OCR on all page images from a Stage 1 output directory.

        Parameters
        ----------
        stage1_dir : path to a Stage 1 output folder containing page images
                     and metadata.json.

        Returns
        -------
        DocumentOCRResult with structured content for the entire document.
        """
        stage1_dir = Path(stage1_dir)

        # Load Stage 1 metadata
        meta_path = stage1_dir / "metadata.json"
        if not meta_path.exists():
            raise FileNotFoundError(
                f"No metadata.json found in {stage1_dir}. "
                "Run Stage 1 first."
            )

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        pdf_path = meta["pdf_path"]
        total_pages = meta["total_pages"]
        doc_name = stage1_dir.name

        logger.info(f"Processing: {doc_name} ({total_pages} pages)")

        # Create output directory
        doc_output_dir = self.output_dir / doc_name
        doc_output_dir.mkdir(parents=True, exist_ok=True)

        converter = self._get_converter()

        result = DocumentOCRResult(
            source_pdf=pdf_path,
            total_pages=total_pages,
        )

        page_image_paths: dict[int, Path] = {}
        for page_meta in meta["pages"]:
            page_num = page_meta["page_num"]
            image_path = Path(page_meta["image_path"])

            # Handle relative paths — Stage 1 saves relative to project root
            if not image_path.is_absolute():
                image_path = Path.cwd() / image_path

            if not image_path.exists():
                logger.warning(f"  Page {page_num}: image not found at {image_path}, skipping")
                continue

            page_image_paths[page_num + 1] = image_path

            logger.info(f"  Page {page_num + 1}/{total_pages}...")

            try:
                page_result = process_image(converter, image_path, page_num)
            except (MemoryError, Exception) as e:
                logger.error(f"    Page {page_num + 1} failed: {e}")
                # Create an empty result for this page so numbering stays correct
                page_result = PageOCRResult(
                    page_num=page_num,
                    elements=[DocumentElement(
                        element_type=ElementType.PARAGRAPH,
                        text=f"[OCR failed for this page: {type(e).__name__}]",
                        page_num=page_num,
                    )],
                    raw_text=f"[OCR failed for this page: {type(e).__name__}]",
                    confidence=None,
                )

            # Log summary
            n_elem = len(page_result.elements)
            n_tables = len(page_result.tables)
            n_headings = len(page_result.headings)
            text_len = len(page_result.raw_text)
            logger.info(
                f"    \u2192 {n_elem} elements, {n_headings} headings, "
                f"{n_tables} tables, {text_len} chars"
            )

            result.pages.append(page_result)

            # Free memory between pages to avoid cumulative MemoryError
            gc.collect()

        # Post-process all pages: numeral normalization, OCR error fixes
        all_quality_flags = []
        all_critical_fields = {"dates": [], "amounts": [], "reference_numbers": []}

        for page in result.pages:
            page.raw_text = postprocess_page_text(page.raw_text)
            for elem in page.elements:
                elem.text = postprocess_page_text(elem.text)

            fields = extract_critical_fields(page.raw_text)
            for key in all_critical_fields:
                for item in fields[key]:
                    if isinstance(item, dict):
                        item["page"] = page.page_num + 1
                    all_critical_fields[key].append(item)
            for flag in fields.get("quality_flags", []):
                all_quality_flags.append(f"Page {page.page_num + 1}: {flag}")

        if all_quality_flags:
            logger.warning(f"Quality flags: {len(all_quality_flags)} issues")
            for flag in all_quality_flags:
                logger.warning(f"  ⚠ {flag}")

        # Attach metadata for JSON output
        result._critical_fields = all_critical_fields
        result._quality_flags = all_quality_flags
        result._page_image_paths = page_image_paths

        # Save outputs
        self._save_outputs(result, doc_output_dir)

        logger.info(f"Done: {doc_name}")
        return result

    def process_all(self, stage1_root: str | Path) -> list[DocumentOCRResult]:
        """Process all document folders in a Stage 1 output directory.

        Parameters
        ----------
        stage1_root : root Stage 1 output directory (e.g., "stage1_output").

        Returns
        -------
        List of DocumentOCRResult, one per document.
        """
        stage1_root = Path(stage1_root)
        results = []

        # Find all document folders (those containing metadata.json)
        doc_dirs = sorted(
            d for d in stage1_root.iterdir()
            if d.is_dir() and (d / "metadata.json").exists()
        )

        if not doc_dirs:
            logger.error(f"No Stage 1 output folders found in {stage1_root}")
            return results

        logger.info(f"Found {len(doc_dirs)} document(s) to process.")

        for i, doc_dir in enumerate(doc_dirs, 1):
            logger.info(f"[{i}/{len(doc_dirs)}] {doc_dir.name}")
            result = self.process(doc_dir)
            results.append(result)

        return results

    def _save_outputs(self, result: DocumentOCRResult, output_dir: Path) -> None:
        """Save OCR results in configured formats."""

        output = result.to_dict()
        # Attach critical fields and quality flags
        output["critical_fields"] = getattr(result, "_critical_fields", {})
        output["quality_flags"] = getattr(result, "_quality_flags", [])

        if "txt" in OUTPUT_FORMATS:
            txt_path = output_dir / "full_text.txt"
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(result.full_text)
            logger.info(f"  Saved: {txt_path}")

        # Confidence sidecar (per-page ocr_score and source only)
        page_confidences = {
            (p.page_num + 1): p.confidence
            for p in result.pages
        }

        # Sarvam fallback OCR for low-confidence pages (per-page)
        page_image_paths = getattr(result, "_page_image_paths", {})
        sarvam_outputs = _run_sarvam_fallback(
            output_dir=output_dir,
            page_image_paths=page_image_paths,
            page_confidences=page_confidences,
            threshold=SARVAM_OCR_THRESHOLD,
        )

        # Build accurate source map based on whether Sarvam succeeded
        source_map = {
            page_no: ("sarvam" if page_no in sarvam_outputs else "docling")
            for page_no in sorted(page_confidences.keys())
        }

        document_name = Path(result.source_pdf).name
        confidence_path = output_dir / f"{document_name}_confidence.json"
        confidence_payload = {
            "pages": [
                {
                    "page_number": page_no,
                    "ocr_score": page_confidences.get(page_no),
                    "source": source_map.get(page_no),
                }
                for page_no in sorted(page_confidences.keys())
            ]
        }

        with open(confidence_path, "w", encoding="utf-8") as f:
            json.dump(confidence_payload, f, indent=2)
        logger.info(f"  Saved: {confidence_path}")

        if "md" in OUTPUT_FORMATS:
            md_path = output_dir / "structured.md"
            merged_md = _merge_markdown(result, sarvam_outputs)
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(merged_md)
            logger.info(f"  Saved: {md_path}")

        if "json" in OUTPUT_FORMATS:
            json_path = output_dir / "structured.json"
            merged_json = _merge_json(output, sarvam_outputs, source_map)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(merged_json, f, indent=2, ensure_ascii=False)
            logger.info(f"  Saved: {json_path}")

        # Cleanup per-page Sarvam files after merge (keep only merged outputs)
        for page_outputs in sarvam_outputs.values():
            md_path = page_outputs.get("md")
            if md_path:
                try:
                    Path(md_path).unlink(missing_ok=True)
                except OSError:
                    logger.warning("  Could not remove %s", md_path)
            json_path = page_outputs.get("json")
            if json_path:
                try:
                    Path(json_path).unlink(missing_ok=True)
                except OSError:
                    logger.warning("  Could not remove %s", json_path)

        # Consolidated confidence log (append-only)
        log_path = self.output_dir / "confidence_log.json"
        log_entries = []
        if log_path.exists():
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    log_entries = json.load(f)
                    if not isinstance(log_entries, list):
                        log_entries = []
            except json.JSONDecodeError:
                log_entries = []

        doc_stem = Path(document_name).stem
        for page_no in sorted(page_confidences.keys()):
            log_entries.append(
                {
                    "document_name": doc_stem,
                    "page_number": page_no,
                    "ocr_score": page_confidences.get(page_no),
                }
            )

        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log_entries, f, indent=2)
        logger.info(f"  Updated: {log_path}")


def _image_to_pdf(image_path: Path, pdf_path: Path) -> None:
    """Create a single-page PDF from a page image."""
    doc = fitz.open()
    img = fitz.open(str(image_path))
    rect = img[0].rect
    page = doc.new_page(width=rect.width, height=rect.height)
    page.insert_image(rect, filename=str(image_path))
    doc.save(str(pdf_path))
    doc.close()
    img.close()


def _downscale_image(image_path: Path, output_path: Path, scale: float) -> None:
    """Downscale an image by a scale factor and save it."""
    img = fitz.open(str(image_path))
    pix = img[0].get_pixmap(matrix=fitz.Matrix(scale, scale))
    pix.save(str(output_path))
    img.close()


def _run_sarvam_fallback(
    output_dir: Path,
    page_image_paths: dict[int, Path],
    page_confidences: dict[int, float | None],
    threshold: float,
) -> dict[int, dict[str, Path]]:
    """Run Sarvam Document Intelligence for low-confidence pages."""
    max_pdf_bytes = 5 * 1024 * 1024
    max_downscale_attempts = 3
    api_key = os.getenv("SARVAM_API_KEY", "")
    if not api_key:
        logger.warning("SARVAM_API_KEY not set; skipping Sarvam OCR fallback.")
        return {}

    try:
        from sarvamai import SarvamAI
    except ImportError:
        logger.warning("sarvamai package not installed; skipping Sarvam OCR fallback.")
        return {}

    client = SarvamAI(api_subscription_key=api_key)

    outputs: dict[int, dict[str, Path]] = {}

    for page_no, score in page_confidences.items():
        if score is None or score >= threshold:
            continue
        image_path = page_image_paths.get(page_no)
        if not image_path or not image_path.exists():
            continue

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            pdf_path = tmpdir_path / f"page_{page_no:04d}.pdf"
            zip_path = tmpdir_path / "output.zip"

            current_image = image_path
            for attempt in range(max_downscale_attempts):
                _image_to_pdf(current_image, pdf_path)
                pdf_size = pdf_path.stat().st_size
                if pdf_size <= max_pdf_bytes:
                    break

                if attempt == max_downscale_attempts - 1:
                    size_mb = pdf_size / (1024 * 1024)
                    logger.warning(
                        "  Page %s: Sarvam input PDF is %.2f MB (> 5 MB) after downscaling; skipping",
                        page_no,
                        size_mb,
                    )
                    current_image = None
                    break

                scale = math.sqrt(max_pdf_bytes / pdf_size) * 0.95
                if scale >= 1.0:
                    scale = 0.9
                scale = max(scale, 0.25)
                scaled_path = tmpdir_path / f"page_{page_no:04d}_scaled_{attempt + 1}.png"
                _downscale_image(current_image, scaled_path, scale)
                current_image = scaled_path

            if current_image is None:
                continue

            job = client.document_intelligence.create_job(
                language="hi-IN",
                output_format="md",
            )
            job.upload_file(str(pdf_path))
            job.start()
            job.wait_until_complete()
            job.download_output(str(zip_path))

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmpdir_path)

            md_files = list(tmpdir_path.rglob("*.md"))
            json_files = list(tmpdir_path.rglob("*.json"))

            if md_files:
                dest_md = output_dir / f"page_{page_no:04d}_sarvam.md"
                shutil.copyfile(md_files[0], dest_md)

            if json_files:
                dest_json = output_dir / f"page_{page_no:04d}_sarvam.json"
                shutil.copyfile(json_files[0], dest_json)

            if md_files or json_files:
                outputs[page_no] = {
                    "md": dest_md if md_files else None,
                    "json": dest_json if json_files else None,
                }

    return outputs


def _merge_markdown(result: DocumentOCRResult, sarvam_outputs: dict[int, dict[str, Path]]) -> str:
    """Merge Docling and Sarvam markdown outputs by page."""
    parts: list[str] = []
    for page in result.pages:
        page_no = page.page_num + 1
        parts.append(f"<!-- Page {page_no} -->")

        sarvam_md = None
        if page_no in sarvam_outputs:
            md_path = sarvam_outputs[page_no].get("md")
            if md_path:
                sarvam_md = Path(md_path).read_text(encoding="utf-8")

        if sarvam_md is not None:
            parts.append(_strip_embedded_images(sarvam_md).strip())
        elif page.raw_text.strip():
            parts.append(page.raw_text)

        parts.append("")

    return "\n\n".join(parts)


def _strip_embedded_images(text: str) -> str:
    """Remove embedded base64 image markdown lines."""
    return "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith("![Image](data:image")
    )


def _merge_json(output: dict, sarvam_outputs: dict[int, dict[str, Path]], source_map: dict[int, str]) -> dict:
    """Merge Docling and Sarvam JSON outputs by page."""
    pages = output.get("pages", [])
    for page in pages:
        page_no = page.get("page_num")
        if page_no in sarvam_outputs:
            md_text = None
            md_path = sarvam_outputs[page_no].get("md")
            if md_path:
                md_text = _strip_embedded_images(Path(md_path).read_text(encoding="utf-8"))

            sarvam_json = None
            json_path = sarvam_outputs[page_no].get("json")
            if json_path:
                try:
                    sarvam_json = json.loads(Path(json_path).read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    sarvam_json = None

            page["text"] = md_text or ""
            page["elements"] = []
            page["num_elements"] = 0
            page["source"] = source_map.get(page_no, "docling")
            page["sarvam_json"] = sarvam_json
        else:
            page["source"] = source_map.get(page_no, "docling")

    return output
