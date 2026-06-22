"""
Stage 2 - OCR and structure extraction.

Default mode skips documents that already have successful structured output in
processed_manifest.json. Use --force to rebuild Stage 2 output safely.
"""

import argparse
import json
import logging
import os
import shutil
import sys
from pathlib import Path

# Windows fix: force huggingface_hub to copy files instead of creating symlinks.
if os.name == "nt":
    import huggingface_hub.file_download as _hf_dl
    _hf_dl.are_symlinks_supported = lambda *args, **kwargs: False

from processing_manifest import (
    find_entry,
    load_manifest,
    make_base_entry,
    save_manifest,
    sha256_file,
    stage2_output_exists,
    upsert_entry,
)


SCRIPT_DIR = Path(__file__).parent
DEFAULT_INPUT = str(SCRIPT_DIR / "stage1_output")
DEFAULT_OUTPUT = str(SCRIPT_DIR / "stage2_output")


def collect_stage1_dirs(input_path: Path) -> list[Path]:
    """Return Stage 1 document folders that contain metadata.json."""
    if (input_path / "metadata.json").exists():
        return [input_path]
    if input_path.is_dir():
        return sorted(
            d for d in input_path.iterdir()
            if d.is_dir() and (d / "metadata.json").exists()
        )
    return []


def read_stage1_metadata(stage1_dir: Path) -> dict:
    """Read the metadata written by Stage 1."""
    with (stage1_dir / "metadata.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def manifest_entry_from_stage1(meta: dict, stage1_dir: Path, pdf_sha256: str) -> dict:
    """Create a manifest entry even when the PDF was already moved away."""
    source_pdf = Path(meta.get("pdf_path", ""))
    if source_pdf.exists():
        return make_base_entry(source_pdf, pdf_sha256)

    now_name = source_pdf.name or f"{stage1_dir.name}.pdf"
    return {
        "pdf_name": now_name,
        "pdf_stem": source_pdf.stem or stage1_dir.name,
        "source_path": str(source_pdf) if str(source_pdf) != "." else "",
        "file_size": None,
        "sha256": pdf_sha256,
        "stage1_status": "success",
        "stage2_status": "",
        "stage1_output_dir": str(stage1_dir),
        "stage2_structured_md": "",
        "stage2_structured_json": "",
        "processed_at": "",
        "updated_at": "",
        "error": None,
    }


def _print_summary(result) -> None:
    logging.info(f"  Document : {result.source_pdf}")
    logging.info(f"  Pages    : {result.total_pages}")
    logging.info(f"  Elements : {len(result.all_elements)}")
    logging.info(f"  Tables   : {len(result.all_tables)}")
    logging.info(f"  Text     : {len(result.full_text)} chars")

    headings = [e for e in result.all_elements if e.element_type.value in ("title", "heading")]
    if headings:
        logging.info("  Headings :")
        for h in headings[:10]:
            logging.info(f"    [{h.element_type.value}] {h.text[:80]}")


def _move_processed_pdf(source_pdf: str) -> None:
    """Move processed PDFs from input_pdfs to used_files for compatibility."""
    src = Path(source_pdf)
    if not src.exists():
        return

    # input_pdfs_dir = (SCRIPT_DIR / "input_pdfs").resolve()
    # try:
    #     source_parent = src.resolve().parent
    # except OSError:
    #     source_parent = src.absolute().parent
    # if source_parent != input_pdfs_dir:
    #     logging.info(f"Keeping source PDF in external corpus: {src}")
    #     return

    used_dir = SCRIPT_DIR / "used_files"
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


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Stage 2 - OCR and structure extraction")
    parser.add_argument("input", type=str, nargs="?", default=DEFAULT_INPUT,
                        help="Stage 1 output folder or root Stage 1 directory")
    parser.add_argument("--output", "-o", type=str, default=DEFAULT_OUTPUT,
                        help="Output directory")
    parser.add_argument("--force", action="store_true", help="Reprocess documents even when output exists")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without writing files")
    parser.add_argument("--limit", type=int, help="Process only the first N eligible documents")
    parser.add_argument("--smart", action="store_true", help="Use smart page-level extraction instead of legacy Stage 2")
    parser.add_argument("--text-confidence-threshold", type=float, default=0.60, help="Smart extraction direct-text threshold")
    parser.add_argument("--ocr-only", action="store_true", help="Smart extraction: force every page through OCR")
    parser.add_argument("--direct-text-only", action="store_true", help="Smart extraction: never invoke OCR")
    parser.add_argument("--verbose", action="store_true", help="Smart extraction: enable debug logging")
    args = parser.parse_args()

    if args.smart:
        from run_smart_extract import main as smart_main

        smart_argv = [str(Path(__file__).with_name("run_smart_extract.py"))]
        smart_input = args.input
        if smart_input == DEFAULT_INPUT:
            smart_input = str(SCRIPT_DIR / "input_pdfs")
        smart_argv.append(smart_input)
        smart_argv.extend(["--output", args.output])
        smart_argv.extend(["--text-confidence-threshold", str(args.text_confidence_threshold)])
        if args.force:
            smart_argv.append("--force")
        if args.dry_run:
            smart_argv.append("--dry-run")
        if args.limit is not None:
            smart_argv.extend(["--limit", str(args.limit)])
        if args.ocr_only:
            smart_argv.append("--ocr-only")
        if args.direct_text_only:
            smart_argv.append("--direct-text-only")
        if args.verbose:
            smart_argv.append("--verbose")
        sys.argv = smart_argv
        smart_main()
        return

    print(
        "DEPRECATION WARNING: legacy Stage 2 OCRs every Stage 1 page image. Use --smart for page-level extraction.",
        file=sys.stderr,
    )

    input_path = Path(args.input)
    output_root = Path(args.output)

    if not input_path.exists():
        logging.error(f"Path not found: {input_path}")
        sys.exit(1)

    doc_dirs = collect_stage1_dirs(input_path)
    if not doc_dirs:
        logging.info("No Stage 1 output folders found.")
        return

    if args.dry_run:
        logging.info("[DRY-RUN] No files will be written.")

    manifest = load_manifest()
    if args.dry_run:
        pipeline = None
    else:
        # Import only for real processing. This keeps --dry-run lightweight and
        # avoids loading OCR/model dependencies when we only want a plan.
        from stage2_ocr import OCRPipeline
        pipeline = OCRPipeline(output_dir=output_root)
    processed_results = []
    eligible_count = 0

    for stage1_dir in doc_dirs:
        entry = None
        try:
            meta = read_stage1_metadata(stage1_dir)
            source_pdf = Path(meta.get("pdf_path", ""))
            pdf_sha256 = meta.get("sha256") or (sha256_file(source_pdf) if source_pdf.exists() else "")
            if not pdf_sha256:
                pdf_sha256 = f"missing-source:{stage1_dir.name}"

            pdf_name = source_pdf.name or f"{stage1_dir.name}.pdf"
            entry = find_entry(manifest, sha256=pdf_sha256, pdf_stem=stage1_dir.name)
            entry = entry or manifest_entry_from_stage1(meta, stage1_dir, pdf_sha256)

            stage2_dir = output_root / stage1_dir.name
            structured_md = stage2_dir / "structured.md"
            structured_json = stage2_dir / "structured.json"
            entry.update({
                "pdf_name": pdf_name,
                "pdf_stem": source_pdf.stem or stage1_dir.name,
                "source_path": str(source_pdf) if str(source_pdf) != "." else entry.get("source_path", ""),
                "sha256": pdf_sha256,
                "stage1_status": entry.get("stage1_status") or "success",
                "stage1_output_dir": str(stage1_dir),
                "stage2_structured_md": str(structured_md),
                "stage2_structured_json": str(structured_json),
            })

            existing_output = structured_md.exists() and structured_json.exists()
            already_done = (
                (entry.get("stage2_status") == "success" and stage2_output_exists(entry))
                or existing_output
            )
            if already_done and not args.force:
                logging.info(f"[SKIP] Stage 2 already processed: {pdf_name}")
                entry.update({
                    "stage2_status": "success",
                    "stage2_structured_md": str(structured_md),
                    "stage2_structured_json": str(structured_json),
                    "error": None,
                })
                if not args.dry_run:
                    upsert_entry(manifest, entry)
                    save_manifest(manifest)
                continue

            eligible_count += 1
            if args.limit is not None and eligible_count > args.limit:
                logging.info(f"[LIMIT] Stage 2 limit reached ({args.limit}); stopping.")
                break

            if args.force and entry:
                logging.info(f"[FORCE] Stage 2 reprocessing: {pdf_name}")
            else:
                logging.info(f"[PROCESS] Stage 2 processing: {pdf_name}")

            if args.dry_run:
                continue

            if args.force and stage2_dir.exists():
                shutil.rmtree(stage2_dir)

            result = pipeline.process(stage1_dir)
            processed_results.append(result)
            _print_summary(result)

            entry.update({
                "stage2_status": "success",
                "stage2_structured_md": str(structured_md),
                "stage2_structured_json": str(structured_json),
                "error": None,
            })
            upsert_entry(manifest, entry)
            save_manifest(manifest)

            _move_processed_pdf(result.source_pdf)
            _cleanup_stage1_dir(stage1_dir)

        except Exception as exc:
            logging.error(f"[ERROR] Stage 2 failed: {stage1_dir.name}: {exc}")
            if entry:
                entry.update({"stage2_status": "failed", "error": str(exc)})
                upsert_entry(manifest, entry)
                save_manifest(manifest)

    if args.dry_run:
        logging.info("[DRY-RUN] Stage 2 check complete.")
        return

    if processed_results:
        total_pages = sum(r.total_pages for r in processed_results)
        total_tables = sum(len(r.all_tables) for r in processed_results)
        logging.info(f"Done - {len(processed_results)} doc(s), {total_pages} pages, {total_tables} tables extracted.")
    else:
        logging.info("No new documents needed Stage 2 processing.")


if __name__ == "__main__":
    main()
