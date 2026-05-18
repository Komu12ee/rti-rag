"""Docling-based OCR and structure extraction.

Processes cleaned page images from Stage 1 through Docling's document
understanding pipeline. Docling simultaneously:
1. Runs OCR on image-based pages (using EasyOCR for Hindi+English)
2. Detects document layout — headings, paragraphs, tables, lists
3. Reconstructs table structure — rows, columns, cell contents

We use two outputs from Docling:
- export_to_markdown() — best overall text + table rendering, used as raw_text
- iterate_items()      — structural metadata (element types, bounding boxes)

For scanned government letters, Docling's layout model sometimes
misclassifies letterhead logos/stamps/lines as "picture" regions.
Since these are text-only scanned docs (no actual photos), we skip
picture elements and treat captions as regular paragraphs.
"""

import logging
import math
import tempfile
from pathlib import Path

from PIL import Image

from docling.document_converter import DocumentConverter, ImageFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
    RapidOcrOptions,
    TesseractOcrOptions,
    PdfPipelineOptions,
    TableStructureOptions,
    TableFormerMode,
)

from .config import (
    OCR_ENGINE, OCR_LANGUAGES, ENABLE_TABLE_STRUCTURE,
    FORCE_FULL_PAGE_OCR, OCR_MAX_PIXELS, OCR_CONFIDENCE_THRESHOLD,
)
from .models import (
    DocumentElement,
    ElementType,
    BoundingBox,
    Table,
    TableCell,
    PageOCRResult,
)

logger = logging.getLogger(__name__)

# Mapping from Docling's label strings to our ElementType enum.
# "picture" and "figure" are deliberately omitted — for scanned govt letters
# these are always logos/stamps/lines, not real images.  "caption" is mapped
# to PARAGRAPH since it's usually real text next to a misdetected "picture".
_LABEL_MAP = {
    "title": ElementType.TITLE,
    "section_header": ElementType.HEADING,
    "section-header": ElementType.HEADING,
    "heading": ElementType.HEADING,
    "text": ElementType.PARAGRAPH,
    "paragraph": ElementType.PARAGRAPH,
    "caption": ElementType.PARAGRAPH,
    "list_item": ElementType.LIST_ITEM,
    "list-item": ElementType.LIST_ITEM,
    "table": ElementType.TABLE,
    "page_header": ElementType.HEADER,
    "page-header": ElementType.HEADER,
    "page_footer": ElementType.FOOTER,
    "page-footer": ElementType.FOOTER,
    "page_number": ElementType.PAGE_NUMBER,
    "formula": ElementType.FORMULA,
}

# Labels to skip entirely — decorative regions on scanned docs
_SKIP_LABELS = {"picture", "figure"}


def _build_converter() -> DocumentConverter:
    """Build a Docling DocumentConverter configured for Hindi+English govt docs."""

    # Select OCR engine
    if OCR_ENGINE == "tesseract":
        ocr_options = TesseractOcrOptions(
            lang=OCR_LANGUAGES,
            force_full_page_ocr=FORCE_FULL_PAGE_OCR,
        )
    elif OCR_ENGINE == "rapidocr":
        ocr_options = RapidOcrOptions(
            lang=OCR_LANGUAGES,
            force_full_page_ocr=FORCE_FULL_PAGE_OCR,
        )
    else:
        ocr_options = EasyOcrOptions(
            lang=OCR_LANGUAGES,
            force_full_page_ocr=FORCE_FULL_PAGE_OCR,
            confidence_threshold=OCR_CONFIDENCE_THRESHOLD,
        )

    # Table structure options
    table_options = TableStructureOptions(
        do_cell_matching=True,
        mode=TableFormerMode.ACCURATE if ENABLE_TABLE_STRUCTURE else TableFormerMode.FAST,
    )

    pipeline_options = PdfPipelineOptions(
        do_ocr=True,
        ocr_options=ocr_options,
        do_table_structure=ENABLE_TABLE_STRUCTURE,
        table_structure_options=table_options,
    )

    converter = DocumentConverter(
        allowed_formats=[InputFormat.IMAGE],
        format_options={
            InputFormat.IMAGE: ImageFormatOption(
                pipeline_options=pipeline_options,
            ),
        },
    )

    return converter


def _map_label(label: str) -> ElementType | None:
    """Map a Docling label string to our ElementType, or None to skip."""
    clean = label.lower().strip()
    if clean in _SKIP_LABELS:
        return None
    return _LABEL_MAP.get(clean, ElementType.UNKNOWN)


def _extract_bbox(item) -> BoundingBox | None:
    """Extract a normalized bounding box from a Docling item."""
    if not (hasattr(item, "prov") and item.prov):
        return None
    prov = item.prov[0] if isinstance(item.prov, list) else item.prov
    if not hasattr(prov, "bbox"):
        return None
    b = prov.bbox
    l = getattr(b, "l", 0)
    t = getattr(b, "t", 0)
    r = getattr(b, "r", 0)
    bot = getattr(b, "b", 0)
    x = min(l, r)
    y = min(t, bot)
    w = abs(r - l)
    h = abs(bot - t)
    return BoundingBox(x=x, y=y, w=w, h=h)


def _extract_table(docling_table) -> Table:
    """Convert a Docling table object to our Table model."""
    table = Table()

    if not hasattr(docling_table, "table") or docling_table.table is None:
        return table

    tbl = docling_table.table
    table.num_rows = tbl.num_rows
    table.num_cols = tbl.num_cols

    for cell_data in tbl.table_cells:
        cell = TableCell(
            row=cell_data.start_row_offset_idx,
            col=cell_data.start_col_offset_idx,
            row_span=cell_data.end_row_offset_idx - cell_data.start_row_offset_idx,
            col_span=cell_data.end_col_offset_idx - cell_data.start_col_offset_idx,
            text=cell_data.text if hasattr(cell_data, "text") else "",
            is_header=getattr(cell_data, "column_header", False),
        )
        table.cells.append(cell)

    return table


def _extract_item_confidence(item) -> float | None:
    """Extract OCR confidence for a Docling item when available."""
    for attr in ("confidence", "conf", "score", "ocr_confidence", "text_confidence"):
        if hasattr(item, attr):
            val = getattr(item, attr)
            if isinstance(val, (int, float)):
                return float(val)

    if hasattr(item, "prov") and item.prov:
        prov = item.prov[0] if isinstance(item.prov, list) else item.prov
        for attr in ("confidence", "score"):
            if hasattr(prov, attr):
                val = getattr(prov, attr)
                if isinstance(val, (int, float)):
                    return float(val)

    return None


def _get_page_ocr_confidence(conv_res, page_num: int) -> float | None:
    """Read page OCR confidence from ConversionResult.confidence."""
    conf_report = getattr(conv_res, "confidence", None)
    if conf_report is None:
        return None

    pages = getattr(conf_report, "pages", None)
    if not pages:
        return None

    if 1 in pages:
        score = getattr(pages[1], "ocr_score", None)
        if score is None:
            return None
        if isinstance(score, float) and math.isnan(score):
            return None
        return float(score)

    return None


def _maybe_downscale(image_path: Path) -> tuple[str, bool]:
    """Downscale image if it exceeds OCR_MAX_PIXELS to prevent MemoryError.

    Returns (path_to_use, is_temp). If downscaled, caller must delete the temp file.
    """
    with Image.open(image_path) as img:
        w, h = img.size
        pixels = w * h

    if pixels <= OCR_MAX_PIXELS:
        return str(image_path), False

    scale = (OCR_MAX_PIXELS / pixels) ** 0.5
    # scale = 1
    new_w = int(w * scale)
    new_h = int(h * scale)
    logger.info(f"    Downscaling {w}x{h} -> {new_w}x{new_h} for OCR")

    with Image.open(image_path) as img:
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp.name
        tmp.close()  # Close before saving — avoids Windows file-lock issues
        resized.save(tmp_path)
        return tmp_path, True


def process_image(
    converter: DocumentConverter,
    image_path: Path,
    page_num: int,
) -> PageOCRResult:
    """Process a single page image through Docling.

    Returns a PageOCRResult where:
    - raw_text is Docling's native markdown (best text quality, includes tables)
    - elements list has the typed structural breakdown (for downstream chunking)
    """
    logger.info(f"    OCR on page {page_num}...")

    # Downscale large images to prevent EasyOCR MemoryError
    ocr_path, is_temp = _maybe_downscale(image_path)
    try:
        result = converter.convert(ocr_path)
    finally:
        if is_temp:
            try:
                Path(ocr_path).unlink()
            except PermissionError:
                # Windows: Docling may still hold the file open briefly
                logger.debug(f"Could not delete temp file {ocr_path} (still locked)")

    doc = result.document

    # --- Primary text: Docling's markdown export (best quality) ---
    raw_text = doc.export_to_markdown()
    # Strip Docling's image placeholders — these are decorative on scanned docs
    cleaned_lines = []
    for line in raw_text.split("\n"):
        stripped = line.strip()
        if stripped == "<!-- image -->" or stripped == "<!-- picture -->":
            continue
        cleaned_lines.append(line)
    raw_text = "\n".join(cleaned_lines).strip()

    # --- Structural elements: for typed breakdown ---
    elements: list[DocumentElement] = []

    for item, _level in doc.iterate_items():
        label_str = getattr(item, "label", "unknown")
        if hasattr(label_str, "value"):
            label_str = label_str.value

        elem_type = _map_label(str(label_str))
        if elem_type is None:
            # Skip picture/figure elements (decorative on scanned docs)
            continue

        text = ""
        if hasattr(item, "text"):
            text = item.text or ""

        # Skip elements with no text (noise)
        if not text.strip() and elem_type != ElementType.TABLE:
            continue

        bbox = _extract_bbox(item)

        # Handle tables — extract full cell structure
        table_obj = None
        if elem_type == ElementType.TABLE:
            table_obj = _extract_table(item)
            if table_obj and table_obj.cells:
                text = table_obj.to_plain_text()
            if not text.strip():
                continue

        # Heading level
        level = 0
        if elem_type in (ElementType.HEADING, ElementType.TITLE):
            level = getattr(item, "level", 1)
            if level == 0:
                level = 1

        elem_confidence = _extract_item_confidence(item)

        elements.append(DocumentElement(
            element_type=elem_type,
            text=text,
            page_num=page_num,
            bbox=bbox,
            level=level,
            table=table_obj,
            confidence=elem_confidence,
        ))

    # Fallback: if iterate_items gave nothing, use the markdown text
    if not elements and raw_text.strip():
        elements.append(DocumentElement(
            element_type=ElementType.PARAGRAPH,
            text=raw_text,
            page_num=page_num,
        ))
        logger.info(f"    Page {page_num}: no structure detected, using full text")

    page_confidence = _get_page_ocr_confidence(result, page_num)

    return PageOCRResult(
        page_num=page_num,
        elements=elements,
        raw_text=raw_text,
        confidence=page_confidence,
    )


def create_converter() -> DocumentConverter:
    """Create and return a configured Docling converter.

    Call once and reuse across pages — loads models only once.
    """
    logger.info("Initializing Docling converter (loading models)...")
    converter = _build_converter()
    logger.info("Docling converter ready.")
    return converter
