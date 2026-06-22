"""
Stage 1 - Image preparation and PDF processing.

Default mode processes only new PDFs. Existing successful work is skipped using
processed_manifest.json. Use --force when you intentionally want to reprocess.
"""

import argparse
import logging
import shutil
import sys
from pathlib import Path

# Add parent directory to path to import config_manager.
sys.path.insert(0, str(Path(__file__).parent.parent))
from config_manager import Config, PathManager

from processing_manifest import (
    find_entry,
    load_manifest,
    make_base_entry,
    save_manifest,
    sha256_file,
    stage1_output_exists,
    stage2_output_exists,
    upsert_entry,
)
from stage1_image_prep import ImagePrepPipeline


logger = logging.getLogger(__name__)


def collect_pdfs(path: Path, quiet_empty: bool = False) -> list[Path]:
    """Collect PDF files from either one PDF path or a folder."""
    if path.is_file() and path.suffix.lower() == ".pdf":
        return [path]
    if path.is_dir():
        pdfs = sorted(path.glob("*.pdf"))
        if not pdfs and not quiet_empty:
            logger.error(f"No PDF files found in {path}")
        return pdfs
    logger.error(f"Not a valid PDF file or directory: {path}")
    return []


def should_skip_stage1(entry: dict | None) -> bool:
    """Return True when this PDF already has usable output.

    Stage 2 success means the document is fully processed. This matters because
    Stage 2 normally deletes the temporary Stage 1 folder after OCR.
    """
    if not entry:
        return False
    if entry.get("stage2_status") in {"success", "completed_smart"} and stage2_output_exists(entry):
        return True
    return entry.get("stage1_status") == "success" and stage1_output_exists(entry)


def existing_stage2_output_for(pdf_stem: str) -> tuple[Path, Path]:
    """Return the default Stage 2 structured output paths for a PDF stem."""
    stage2_dir = Path(__file__).parent / "stage2_output" / pdf_stem
    return stage2_dir / "structured.md", stage2_dir / "structured.json"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Stage 1 - PDF image preparation")
    parser.add_argument("input", type=str, nargs="?", help="PDF file or folder containing PDFs")
    parser.add_argument("--output", "-o", type=str, help="Output directory for processed images")
    parser.add_argument("--mask-stamps", type=bool, default=True, help="Mask stamps in output")
    parser.add_argument("--save-debug", type=bool, default=False, help="Save debug images")
    parser.add_argument("--config", "-c", type=str, help="Configuration file (JSON)")
    parser.add_argument("--show-config", action="store_true", help="Display configuration and exit")
    parser.add_argument("--force", action="store_true", help="Reprocess PDFs even when output exists")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without writing files")
    parser.add_argument("--limit", type=int, help="Process only the first N eligible PDFs")
    parser.add_argument("--smart", action="store_true", help="Use smart page-level extraction instead of legacy Stage 1")
    parser.add_argument("--text-confidence-threshold", type=float, default=0.60, help="Smart extraction direct-text threshold")
    parser.add_argument("--ocr-only", action="store_true", help="Smart extraction: force every page through OCR")
    parser.add_argument("--direct-text-only", action="store_true", help="Smart extraction: never invoke OCR")
    parser.add_argument("--verbose", action="store_true", help="Smart extraction: enable debug logging")
    args = parser.parse_args()

    if args.smart:
        from run_smart_extract import main as smart_main

        smart_argv = [str(Path(__file__).with_name("run_smart_extract.py"))]
        if args.input:
            smart_argv.append(args.input)
        if args.output:
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
        "DEPRECATION WARNING: legacy Stage 1 rasterizes every page. Use --smart for page-level extraction.",
        file=sys.stderr,
    )

    config = Config(stage="preprocessing")
    if args.config:
        file_config = Config.load_from_file(args.config)
        config.config_dict.update(file_config)
    if args.input:
        config.config_dict["input_dir"] = args.input
    if args.output:
        config.config_dict["output_dir"] = args.output

    if args.show_config:
        config.log_config()
        return

    input_path = Path(config.get_input_path(as_str=True))
    output_path = Path(config.get_output_path(as_str=True))

    logger.info("Stage 1: Image Preparation")
    logger.info(f"Input: {input_path}")
    logger.info(f"Output: {output_path}")
    if args.dry_run:
        logger.info("[DRY-RUN] No files will be written.")
    else:
        PathManager.ensure_dirs(str(output_path))

    if not input_path.exists():
        logger.error(f"Input path does not exist: {input_path}")
        sys.exit(1)

    pdfs = collect_pdfs(input_path, quiet_empty=args.dry_run)
    if not pdfs:
        if args.dry_run:
            logger.info("[DRY-RUN] No PDFs found.")
            return
        sys.exit(1)

    pipeline = ImagePrepPipeline(
        output_dir=output_path,
        mask_stamps_in_output=args.mask_stamps,
        save_debug_images=args.save_debug,
    )

    manifest = load_manifest()
    all_results = []
    eligible_count = 0

    for pdf_path in pdfs:
        pdf_hash = sha256_file(pdf_path)
        entry = find_entry(manifest, sha256=pdf_hash, pdf_stem=pdf_path.stem)
        stage1_dir = output_path / pdf_path.stem
        existing_md, existing_json = existing_stage2_output_for(pdf_path.stem)

        if should_skip_stage1(entry) and not args.force:
            logger.info(f"[SKIP] Stage 1 already processed: {pdf_path.name}")
            continue
        if not entry and existing_md.exists() and existing_json.exists() and not args.force:
            logger.info(f"[SKIP] Stage 1 already processed: {pdf_path.name}")
            entry = make_base_entry(pdf_path, pdf_hash)
            entry.update({
                "stage1_status": "skipped",
                "stage2_status": "success",
                "stage2_structured_md": str(existing_md),
                "stage2_structured_json": str(existing_json),
                "error": None,
            })
            if not args.dry_run:
                upsert_entry(manifest, entry)
                save_manifest(manifest)
            continue
        if not entry and (stage1_dir / "metadata.json").exists() and not args.force:
            logger.info(f"[SKIP] Stage 1 already processed: {pdf_path.name}")
            entry = make_base_entry(pdf_path, pdf_hash)
            entry.update({
                "stage1_status": "success",
                "stage1_output_dir": str(stage1_dir),
                "error": None,
            })
            if not args.dry_run:
                upsert_entry(manifest, entry)
                save_manifest(manifest)
            continue

        eligible_count += 1
        if args.limit is not None and eligible_count > args.limit:
            logger.info(f"[LIMIT] Stage 1 limit reached ({args.limit}); stopping.")
            break

        if args.force and entry:
            logger.info(f"[FORCE] Stage 1 reprocessing: {pdf_path.name}")
        else:
            logger.info(f"[PROCESS] Stage 1 processing: {pdf_path.name}")

        if args.dry_run:
            continue

        try:
            # A forced run starts from clean Stage 1 page images for this PDF.
            if args.force and stage1_dir.exists():
                shutil.rmtree(stage1_dir)

            result = pipeline.process(pdf_path, pdf_sha256=pdf_hash)
            all_results.append(result)

            entry = entry or make_base_entry(pdf_path, pdf_hash)
            entry.update({
                "pdf_name": pdf_path.name,
                "pdf_stem": pdf_path.stem,
                "source_path": str(pdf_path),
                "file_size": pdf_path.stat().st_size,
                "sha256": pdf_hash,
                "stage1_status": "success",
                "stage1_output_dir": str(stage1_dir),
                "error": None,
            })
            upsert_entry(manifest, entry)
            save_manifest(manifest)

            stamps_pages = sum(1 for p in result.pages if p.has_stamps)
            skewed_pages = sum(1 for p in result.pages if p.skew_angle != 0.0)
            logger.info(f"  {result.total_pages} pages | {skewed_pages} deskewed | {stamps_pages} with stamps")
        except Exception as exc:
            logger.error(f"[ERROR] Stage 1 failed: {pdf_path.name}: {exc}")
            entry = entry or make_base_entry(pdf_path, pdf_hash)
            entry.update({
                "stage1_status": "failed",
                "stage1_output_dir": str(stage1_dir),
                "error": str(exc),
            })
            upsert_entry(manifest, entry)
            save_manifest(manifest)

    if args.dry_run:
        logger.info("[DRY-RUN] Stage 1 check complete.")
        return

    if all_results:
        total_pages = sum(r.total_pages for r in all_results)
        total_stamps = sum(sum(p.stamp_count for p in r.pages) for r in all_results)
        logger.info(f"Done - {len(all_results)} PDF(s), {total_pages} pages, {total_stamps} stamps detected.")
    else:
        logger.info("No new PDFs needed Stage 1 processing.")


if __name__ == "__main__":
    main()
