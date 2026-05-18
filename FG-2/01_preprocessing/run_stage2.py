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
import shutil
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
        _move_processed_pdf(result.source_pdf)
        _cleanup_stage1_dir(input_path)
    else:
        # Root directory with multiple documents
        logging.info(f"Processing all documents in: {input_path}")
        results = pipeline.process_all(input_path)
        for result in results:
            _print_summary(result)
            _move_processed_pdf(result.source_pdf)
            doc_dir = input_path / Path(result.source_pdf).stem
            if doc_dir.exists():
                _cleanup_stage1_dir(doc_dir)
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


def _move_processed_pdf(source_pdf: str) -> None:
    """Move processed PDFs from input_pdfs to used_files."""
    src = Path(source_pdf)
    if not src.exists():
        return

    used_dir = Path(__file__).parent / "used_files"
    used_dir.mkdir(parents=True, exist_ok=True)

    dest = used_dir / src.name
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        counter = 1
        while True:
            candidate = used_dir / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                dest = candidate
                break
            counter += 1

    try:
        shutil.move(str(src), str(dest))
        logging.info(f"Moved source PDF to used_files: {dest}")
    except OSError as exc:
        logging.warning(f"Could not move source PDF {src} to used_files: {exc}")


def _cleanup_stage1_dir(stage1_dir: Path) -> None:
    """Remove Stage 1 output folder after Stage 2 completes."""
    if not stage1_dir.exists():
        return

    try:
        shutil.rmtree(stage1_dir)
        logging.info(f"Removed Stage 1 output: {stage1_dir}")
    except OSError as exc:
        logging.warning(f"Could not remove Stage 1 output {stage1_dir}: {exc}")


if __name__ == "__main__":
    main()