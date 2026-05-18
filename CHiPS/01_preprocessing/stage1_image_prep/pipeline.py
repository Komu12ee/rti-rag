"""Orchestration pipeline — runs all Stage 1 steps on a PDF.

For each page:  PDF → Image (450 DPI) → Deskew → Denoise → Stamp Detection

Produces a per-page result with the cleaned image and metadata, plus saves
processed images to disk for Stage 2 (OCR) to consume.
"""

import json
import logging
import cv2
import numpy as np
from dataclasses import dataclass, field, asdict
from pathlib import Path
from PIL import Image

from .config import DEFAULT_OUTPUT_DIR, IMAGE_FORMAT, DPI
from .pdf_to_image import pdf_to_images, get_page_count
from .deskew import deskew
from .denoise import denoise
from .stamp_detector import detect_stamps, mask_stamps, StampDetectionResult

logger = logging.getLogger(__name__)


@dataclass
class PageResult:
    """Processing result for a single page."""

    page_num: int  # zero-indexed
    skew_angle: float
    noise_stats: dict = field(default_factory=dict)
    has_stamps: bool = False
    has_handwriting: bool = False
    stamp_count: int = 0
    stamp_regions: list[dict] = field(default_factory=list)
    image_path: str = ""  # path where cleaned image was saved


@dataclass
class DocumentResult:
    """Processing result for an entire PDF."""

    pdf_path: str
    total_pages: int
    pages: list[PageResult] = field(default_factory=list)


class ImagePrepPipeline:
    """Stage 1 pipeline: prepare PDF page images for OCR.

    Usage
    -----
    >>> pipeline = ImagePrepPipeline(output_dir="stage1_output")
    >>> result = pipeline.process("document.pdf")
    >>> for page in result.pages:
    ...     print(f"Page {page.page_num}: skew={page.skew_angle}°, stamps={page.stamp_count}")
    """

    def __init__(
        self,
        output_dir: str | Path = DEFAULT_OUTPUT_DIR,
        mask_stamps_in_output: bool = True,
        save_debug_images: bool = False,
    ):
        """
        Parameters
        ----------
        output_dir : directory to save processed images and metadata.
        mask_stamps_in_output : if True, stamp regions are whited out in saved images.
        save_debug_images : if True, saves intermediate images (deskewed, etc.) for debugging.
        """
        self.output_dir = Path(output_dir)
        self.mask_stamps_in_output = mask_stamps_in_output
        self.save_debug_images = save_debug_images

    def process(self, pdf_path: str | Path) -> DocumentResult:
        """Run the full Stage 1 pipeline on a PDF.

        Parameters
        ----------
        pdf_path : path to the input PDF file.

        Returns
        -------
        DocumentResult with per-page metadata and paths to cleaned images.
        """
        pdf_path = Path(pdf_path)
        logger.info(f"Processing: {pdf_path.name}")

        # Create output directory structure
        doc_name = pdf_path.stem
        doc_output_dir = self.output_dir / doc_name
        doc_output_dir.mkdir(parents=True, exist_ok=True)

        if self.save_debug_images:
            debug_dir = doc_output_dir / "debug"
            debug_dir.mkdir(exist_ok=True)

        # Step 1: Convert all pages to images
        logger.info(f"  Converting PDF to images at {DPI} DPI...")
        page_images = pdf_to_images(pdf_path)
        total_pages = len(page_images)
        logger.info(f"  {total_pages} pages converted.")

        result = DocumentResult(
            pdf_path=str(pdf_path),
            total_pages=total_pages,
        )

        for page_num, raw_image in enumerate(page_images):
            logger.info(f"  Page {page_num + 1}/{total_pages}...")
            page_result = self._process_page(
                raw_image, page_num, doc_output_dir
            )
            result.pages.append(page_result)

        # Save metadata JSON
        metadata_path = doc_output_dir / "metadata.json"
        self._save_metadata(result, metadata_path)
        logger.info(f"  Metadata saved to {metadata_path}")
        logger.info(f"Done: {pdf_path.name} — {total_pages} pages processed.")

        return result

    def _process_page(
        self,
        raw_image: np.ndarray,
        page_num: int,
        doc_output_dir: Path,
    ) -> PageResult:
        """Process a single page through all Stage 1 steps."""

        debug_dir = doc_output_dir / "debug" if self.save_debug_images else None

        # --- Deskew ---
        deskewed, skew_angle = deskew(raw_image)
        if skew_angle != 0.0:
            logger.info(f"    Deskewed by {skew_angle:.2f}°")
        if debug_dir:
            cv2.imwrite(
                str(debug_dir / f"page_{page_num:04d}_deskewed.{IMAGE_FORMAT}"),
                deskewed,
            )

        # --- Denoise ---
        # Disabled to preserve tiny punctuation and micro-components.
        denoised = deskewed
        noise_stats = {
            "speckles_removed": 0,
            "noise_ratio": 0.0,
            "denoise_disabled": True,
        }
        if debug_dir:
            cv2.imwrite(
                str(debug_dir / f"page_{page_num:04d}_denoised.{IMAGE_FORMAT}"),
                denoised,
            )

        # --- Stamp Detection ---
        stamp_result: StampDetectionResult = detect_stamps(deskewed)
        stamp_regions_dicts = []
        if stamp_result.has_stamps:
            logger.info(
                f"    Detected {len(stamp_result.regions)} stamp/annotation region(s)"
            )
            for r in stamp_result.regions:
                stamp_regions_dicts.append({
                    "x": r.x, "y": r.y, "w": r.w, "h": r.h,
                    "color": r.color_name,
                    "area_ratio": r.area_ratio,
                    "is_circular": r.is_circular,
                    "confidence": r.confidence,
                })

        # --- Final output image ---
        final_image = denoised
        if self.mask_stamps_in_output and stamp_result.mask is not None:
            final_image = mask_stamps(denoised, stamp_result.mask)

        # Save cleaned image using PIL (handles Unicode paths better than cv2)
        image_filename = f"page_{page_num:04d}.{IMAGE_FORMAT}"
        image_path = doc_output_dir / image_filename
        
        # Convert BGR (OpenCV) to RGB for PIL
        if len(final_image.shape) == 3:
            final_image_rgb = cv2.cvtColor(final_image, cv2.COLOR_BGR2RGB)
        else:
            final_image_rgb = final_image
        
        pil_image = Image.fromarray(final_image_rgb)
        pil_image.save(str(image_path))
        
        # Verify write succeeded
        if not image_path.exists():
            logger.error(f"    Failed to save image to {image_path}")
        else:
            logger.debug(f"    Saved image to {image_path}")

        return PageResult(
            page_num=page_num,
            skew_angle=round(skew_angle, 3),
            noise_stats=noise_stats,
            has_stamps=stamp_result.has_stamps,
            has_handwriting=stamp_result.has_handwriting,
            stamp_count=len(stamp_result.regions),
            stamp_regions=stamp_regions_dicts,
            image_path=str(image_path),
        )

    @staticmethod
    def _save_metadata(result: DocumentResult, path: Path) -> None:
        """Save document processing metadata as JSON."""
        data = {
            "pdf_path": result.pdf_path,
            "total_pages": result.total_pages,
            "pages": [asdict(p) for p in result.pages],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
