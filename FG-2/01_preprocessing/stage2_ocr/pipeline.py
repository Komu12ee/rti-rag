"""Stage 2 orchestration pipeline.

Takes Stage 1 output (cleaned images + metadata) and runs Docling OCR on
each page. Produces structured document output with headings, paragraphs,
tables, and lists properly identified.

Reads from: stage1_output/<doc_name>/page_XXXX.png + metadata.json
Writes to:  stage2_output/<doc_name>/structured.json + structured.md
"""

import gc
import json
import logging
from pathlib import Path

from .config import DEFAULT_OUTPUT_DIR, OUTPUT_FORMATS
from .docling_ocr import create_converter, process_image
from .models import DocumentOCRResult, PageOCRResult, DocumentElement, ElementType
from .postprocess import postprocess_page_text, extract_critical_fields

logger = logging.getLogger(__name__)


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

        for page_meta in meta["pages"]:
            page_num = page_meta["page_num"]
            image_path = Path(page_meta["image_path"])

            # Handle relative paths — Stage 1 saves relative to project root
            if not image_path.is_absolute():
                image_path = Path.cwd() / image_path

            if not image_path.exists():
                logger.warning(f"  Page {page_num}: image not found at {image_path}, skipping")
                continue

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

        if "json" in OUTPUT_FORMATS:
            json_path = output_dir / "structured.json"
            output = result.to_dict()
            # Attach critical fields and quality flags
            output["critical_fields"] = getattr(result, "_critical_fields", {})
            output["quality_flags"] = getattr(result, "_quality_flags", [])
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, ensure_ascii=False)
            logger.info(f"  Saved: {json_path}")

        if "md" in OUTPUT_FORMATS:
            md_path = output_dir / "structured.md"
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(result.to_markdown())
            logger.info(f"  Saved: {md_path}")

        if "txt" in OUTPUT_FORMATS:
            txt_path = output_dir / "full_text.txt"
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(result.full_text)
            logger.info(f"  Saved: {txt_path}")
