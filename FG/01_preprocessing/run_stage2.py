"""
Stage 2 — OCR and Structure Extraction
Run on Stage 1 output (cleaned images).
Usage:
    python run_stage2.py
    python run_stage2.py path/to/stage1_output/
    python run_stage2.py path/to/stage1_output/ -o my_ocr_output/
"""
import argparse
import logging
import os
import sys
from pathlib import Path

# Windows fix: force huggingface_hub to copy files instead of creating symlinks
if os.name == "nt":
    import huggingface_hub.file_download as _hf_dl
    _hf_dl.are_symlinks_supported = lambda *args, **kwargs: False

from stage2_ocr import OCRPipeline


# ── Config (edit these defaults if needed) ────────────────────────────────────
# Use relative paths for Docker compatibility
_SCRIPT_DIR = Path(__file__).parent
DEFAULT_INPUT  = str(_SCRIPT_DIR / "stage1_output")  # e.g. r"D:\docs\stage1_output"
DEFAULT_OUTPUT = str(_SCRIPT_DIR / "stage2_output")  # e.g. r"D:\docs\stage2_output" (leave "" to use "stage2_output")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Stage 2 — OCR and Structure Extraction"
    )
    parser.add_argument("input", type=str, nargs="?", default=DEFAULT_INPUT,
                        help="Stage 1 output folder (single doc) or root Stage 1 directory")
    parser.add_argument("--output", "-o", type=str,
                        default=DEFAULT_OUTPUT or "stage2_output",
                        help="Output directory (default: stage2_output)")
    args = parser.parse_args()

    if not args.input:
        logging.error("No input path provided. Set DEFAULT_INPUT in the script or pass it as an argument.")
        sys.exit(1)

    input_path = Path(args.input)
    if not input_path.exists():
        logging.error(f"Path not found: {input_path}")
        sys.exit(1)

    pipeline = OCRPipeline(output_dir=args.output)

    if (input_path / "metadata.json").exists():
        # Single document
        logging.info(f"Processing single document: {input_path.name}")
        result = pipeline.process(input_path)
        _print_summary(result)
    else:
        # Root directory with multiple documents
        logging.info(f"Processing all documents in: {input_path}")
        results = pipeline.process_all(input_path)
        for result in results:
            _print_summary(result)
        total_pages  = sum(r.total_pages for r in results)
        total_tables = sum(len(r.all_tables) for r in results)
        logging.info(f"Done — {len(results)} doc(s), {total_pages} pages, {total_tables} tables extracted.")


def _print_summary(result):
    logging.info(f"  Document : {result.source_pdf}")
    logging.info(f"  Pages    : {result.total_pages}")
    logging.info(f"  Elements : {len(result.all_elements)}")
    logging.info(f"  Tables   : {len(result.all_tables)}")
    logging.info(f"  Text     : {len(result.full_text)} chars")

    headings = [e for e in result.all_elements if e.element_type.value in ("title", "heading")]
    if headings:
        logging.info(f"  Headings :")
        for h in headings[:10]:
            logging.info(f"    [{h.element_type.value}] {h.text[:80]}")


if __name__ == "__main__":
    main()