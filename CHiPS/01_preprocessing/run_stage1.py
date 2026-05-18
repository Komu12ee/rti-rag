"""
Stage 1 — Image Preparation and PDF Processing
Converts PDFs to images and applies OCR preprocessing.

Usage:
    python run_stage1.py                              # Use default paths
    python run_stage1.py /path/to/document.pdf       # Process single PDF
    python run_stage1.py /path/to/pdf_folder/        # Process all PDFs in folder
    python run_stage1.py -o /custom/output/          # Specify output directory
    python run_stage1.py --config config.json        # Load from config file
    python run_stage1.py --show-config               # Display current configuration
"""
import argparse
import logging
import sys
from pathlib import Path

# Add parent directory to path to import config_manager
sys.path.insert(0, str(Path(__file__).parent.parent))
from config_manager import Config, PathManager

from stage1_image_prep import ImagePrepPipeline


logger = logging.getLogger(__name__)


def collect_pdfs(path: Path) -> list[Path]:
    """Collect all PDF files from path (file or directory)."""
    if path.is_file() and path.suffix.lower() == ".pdf":
        return [path]
    if path.is_dir():
        pdfs = sorted(path.glob("*.pdf"))
        if not pdfs:
            logger.error(f"No PDF files found in {path}")
            return []
        return pdfs
    logger.error(f"Not a valid PDF file or directory: {path}")
    return []


def main():
    """Main entry point with configuration support."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Stage 1 — PDF Image Preparation and OCR Preprocessing"
    )
    parser.add_argument("input", type=str, nargs="?",
                       help="PDF file or folder containing PDFs")
    parser.add_argument("--output", "-o", type=str,
                       help="Output directory for processed images")
    parser.add_argument("--mask-stamps", type=bool, default=True,
                       help="Mask stamps in output (default: True)")
    parser.add_argument("--save-debug", type=bool, default=False,
                       help="Save debug images (default: False)")
    parser.add_argument("--config", "-c", type=str,
                       help="Configuration file (JSON)")
    parser.add_argument("--show-config", action="store_true",
                       help="Display configuration and exit")
    args = parser.parse_args()

    # Load configuration
    config = Config(stage='preprocessing')
    
    # Override with config file if provided
    if args.config:
        file_config = Config.load_from_file(args.config)
        config.config_dict.update(file_config)
    
    # Override with command-line arguments
    if args.input:
        config.config_dict['input_dir'] = args.input
    if args.output:
        config.config_dict['output_dir'] = args.output
    
    # Show configuration if requested
    if args.show_config:
        config.log_config()
        return
    
    # Get paths
    input_path_str = config.get_input_path(as_str=True)
    output_path_str = config.get_output_path(as_str=True)
    
    logger.info(f"Stage 1: Image Preparation")
    logger.info(f"Input: {input_path_str}")
    logger.info(f"Output: {output_path_str}")
    
    # Create output directory
    PathManager.ensure_dirs(output_path_str)
    
    # Collect PDFs
    input_path = Path(input_path_str)
    if not input_path.exists():
        logger.error(f"Input path does not exist: {input_path}")
        sys.exit(1)
    
    pdfs = collect_pdfs(input_path)
    if not pdfs:
        logger.error("No PDF files found to process")
        sys.exit(1)
    
    # Initialize pipeline
    pipeline = ImagePrepPipeline(
        output_dir=output_path_str,
        mask_stamps_in_output=args.mask_stamps,
        save_debug_images=args.save_debug,
    )
    
    logger.info(f"Found {len(pdfs)} PDF(s) → {Path(output_path_str).resolve()}")
    
    # Process all PDFs
    all_results = []
    for i, pdf_path in enumerate(pdfs, 1):
        logger.info(f"[{i}/{len(pdfs)}] {pdf_path.name}")
        try:
            result = pipeline.process(pdf_path)
            all_results.append(result)

            if hasattr(result, 'pages'):
                stamps_pages = sum(1 for p in result.pages if hasattr(p, 'has_stamps') and p.has_stamps)
                skewed_pages = sum(1 for p in result.pages if hasattr(p, 'skew_angle') and p.skew_angle != 0.0)
                logger.info(f"  {result.total_pages} pages | {skewed_pages} deskewed | {stamps_pages} with stamps")
            else:
                logger.info(f"  Processed successfully")
        except Exception as e:
            logger.error(f"Error processing {pdf_path.name}: {e}")
            continue

    # Summary
    if all_results:
        total_pages = sum(r.total_pages for r in all_results if hasattr(r, 'total_pages'))
        total_stamps = sum(
            sum(p.stamp_count for p in r.pages if hasattr(p, 'stamp_count'))
            for r in all_results if hasattr(r, 'pages')
        )
        logger.info(f"\n✅ Done — {len(pdfs)} PDF(s), {total_pages} pages, {total_stamps} stamps detected.")
    else:
        logger.warning("No PDFs were successfully processed.")
        sys.exit(1)


if __name__ == "__main__":
    main()