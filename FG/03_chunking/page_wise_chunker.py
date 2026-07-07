"""
Stage 3: Strict page-wise chunking.

Rule:
    One OCR page = one chunk.

Input:
    structured.md containing markers like:

    <!-- Page 1 -->
    page 1 content...

    <!-- Page 2 -->
    page 2 content...

Output:
    output/<document_name>/page_0001.txt
    output/<document_name>/page_0002.txt
    output/<document_name>/page_chunks_metadata.json

No Docling, transformers, tokenizer, or semantic chunking is used here.
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# Matches:
# <!-- Page 1 -->
# <!--Page 12-->
# <!-- page 25 -->
PAGE_MARKER_PATTERN = re.compile(
    r"<!--\s*page\s+(\d+)\s*-->",
    re.IGNORECASE,
)


def load_confidence_data(confidence_json: Optional[Path]) -> Dict[int, dict]:
    """
    Load page-level OCR confidence data.

    Expected structure:
    {
      "pages": [
        {
          "page_number": 1,
          ...
        }
      ]
    }
    """
    if not confidence_json or not confidence_json.exists():
        return {}

    try:
        with confidence_json.open("r", encoding="utf-8") as file:
            data = json.load(file)

        page_map = {}

        for page in data.get("pages", []):
            page_number = page.get("page_number")

            if page_number is None:
                continue

            page_map[int(page_number)] = page

        logger.info(
            "Loaded confidence metadata for %s page(s)",
            len(page_map),
        )

        return page_map

    except Exception as error:
        logger.warning(
            "Could not load confidence JSON %s: %s",
            confidence_json,
            error,
        )
        return {}


def split_markdown_by_page(markdown_text: str) -> List[Dict]:
    """
    Split structured markdown using <!-- Page X --> markers.

    Returns one item per physical page.
    """

    markers = list(PAGE_MARKER_PATTERN.finditer(markdown_text))

    # Fallback: no page marker means the whole file becomes one chunk.
    if not markers:
        logger.warning(
            "No '<!-- Page X -->' markers found. "
            "Creating one fallback chunk as Page 1."
        )
        return [
            {
                "page_number": 1,
                "text": markdown_text.strip(),
            }
        ]

    page_chunks = []

    # Content before Page 1 marker is usually title/preamble.
    # Attach it to Page 1 instead of losing it.
    preamble = markdown_text[: markers[0].start()].strip()

    for index, marker in enumerate(markers):
        page_number = int(marker.group(1))

        content_start = marker.end()

        if index + 1 < len(markers):
            content_end = markers[index + 1].start()
        else:
            content_end = len(markdown_text)

        page_text = markdown_text[content_start:content_end].strip()

        if index == 0 and preamble:
            page_text = f"{preamble}\n\n{page_text}".strip()

        if not page_text:
            logger.warning(
                "Page %s has no extracted text. "
                "An empty page chunk will still be created.",
                page_number,
            )

        page_chunks.append(
            {
                "page_number": page_number,
                "text": page_text,
            }
        )

    return page_chunks


def find_confidence_file(document_dir: Path) -> Optional[Path]:
    """
    Find confidence JSON for a document folder.

    Preferred pattern:
        <folder_name>.pdf_confidence.json
    """

    preferred_file = document_dir / f"{document_dir.name}.pdf_confidence.json"

    if preferred_file.exists():
        return preferred_file

    candidates = sorted(document_dir.glob("*_confidence.json"))

    if candidates:
        return candidates[0]

    return None


def write_page_chunks(
    structured_md: Path,
    output_root: Path,
    warning_char_limit: int,
) -> int:
    """
    Create exactly one output .txt file per page marker.
    """

    document_dir = structured_md.parent
    document_name = document_dir.name
    output_dir = output_root / document_name

    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 80)
    logger.info("Processing document: %s", document_name)
    logger.info("Source markdown: %s", structured_md)

    markdown_text = structured_md.read_text(
        encoding="utf-8",
        errors="replace",
    )

    page_chunks = split_markdown_by_page(markdown_text)

    confidence_json = find_confidence_file(document_dir)
    confidence_by_page = load_confidence_data(confidence_json)

    metadata = {
        "document_name": document_name,
        "source_markdown": str(structured_md),
        "chunking_strategy": "strict_one_page_one_chunk",
        "total_chunks": len(page_chunks),
        "confidence_file": str(confidence_json) if confidence_json else None,
        "chunks": [],
    }

    for chunk_index, page_chunk in enumerate(page_chunks, start=1):
        page_number = page_chunk["page_number"]
        page_text = page_chunk["text"]

        output_file = output_dir / f"page_{page_number:04d}.txt"

        # Keep chunk text clean.
        # Metadata is stored separately in page_chunks_metadata.json.
        output_file.write_text(
            page_text + "\n",
            encoding="utf-8",
        )

        character_count = len(page_text)
        word_count = len(re.findall(r"\S+", page_text))

        if character_count > warning_char_limit:
            logger.warning(
                "Page %s is large: %s characters. "
                "It remains one chunk because page-wise mode is strict.",
                page_number,
                character_count,
            )

        metadata["chunks"].append(
            {
                "chunk_index": chunk_index,
                "page_number": page_number,
                "filename": output_file.name,
                "character_count": character_count,
                "word_count": word_count,
                "page_confidence": confidence_by_page.get(page_number),
            }
        )

        logger.info(
            "Created chunk %s | Page %s | %s chars | %s words",
            chunk_index,
            page_number,
            character_count,
            word_count,
        )

    metadata_path = output_dir / "page_chunks_metadata.json"

    with metadata_path.open("w", encoding="utf-8") as file:
        json.dump(
            metadata,
            file,
            indent=2,
            ensure_ascii=False,
        )

    logger.info(
        "Completed: %s page chunks saved in %s",
        len(page_chunks),
        output_dir,
    )

    return len(page_chunks)


def get_documents_to_process(
    input_path: Path,
    document_name: Optional[str],
) -> List[Tuple[Path, Path]]:
    """
    Supports three input forms:

    1. A stage2_output directory containing many document folders.
    2. One document folder containing structured.md.
    3. A direct path to structured.md.
    """

    documents = []

    if not input_path.exists():
        raise FileNotFoundError(f"Input path not found: {input_path}")

    # Direct structured.md input.
    if input_path.is_file():
        if input_path.name != "structured.md":
            raise ValueError(
                "When --input is a file, it must point to structured.md"
            )

        documents.append((input_path.parent, input_path))
        return documents

    # Specific document folder inside stage2_output.
    if document_name:
        document_dir = input_path / document_name
        structured_md = document_dir / "structured.md"

        if not structured_md.exists():
            raise FileNotFoundError(
                f"structured.md not found: {structured_md}"
            )

        documents.append((document_dir, structured_md))
        return documents

    # Input itself is a single document folder.
    direct_structured_md = input_path / "structured.md"

    if direct_structured_md.exists():
        documents.append((input_path, direct_structured_md))
        return documents

    # Input is stage2_output containing multiple document folders.
    for child in sorted(input_path.iterdir()):
        if not child.is_dir():
            continue

        structured_md = child / "structured.md"

        if structured_md.exists():
            documents.append((child, structured_md))

    return documents


def main():
    parser = argparse.ArgumentParser(
        description="Create strict page-wise chunks from structured.md"
    )

    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help=(
            "Path to stage2_output folder, one document folder, "
            "or a direct structured.md file"
        ),
    )

    parser.add_argument(
        "--output",
        "-o",
        default="page_wise_chunks_output",
        help="Output root directory for generated page chunks",
    )

    parser.add_argument(
        "--document",
        "-d",
        default=None,
        help=(
            "Specific document folder name inside stage2_output. "
            "Optional."
        ),
    )

    parser.add_argument(
        "--warning-char-limit",
        type=int,
        default=18000,
        help=(
            "Log a warning if one page exceeds this many characters. "
            "Page will not be split."
        ),
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    output_root = Path(args.output)

    try:
        documents = get_documents_to_process(
            input_path=input_path,
            document_name=args.document,
        )

        if not documents:
            logger.error(
                "No structured.md files found under: %s",
                input_path,
            )
            sys.exit(1)

        logger.info("=" * 80)
        logger.info("Strict Page-Wise Chunking Started")
        logger.info("Input: %s", input_path)
        logger.info("Output: %s", output_root)
        logger.info("Documents found: %s", len(documents))
        logger.info("=" * 80)

        total_chunks = 0

        for _, structured_md in documents:
            total_chunks += write_page_chunks(
                structured_md=structured_md,
                output_root=output_root,
                warning_char_limit=args.warning_char_limit,
            )

        logger.info("=" * 80)
        logger.info(
            "Chunking completed successfully. Total page chunks: %s",
            total_chunks,
        )
        logger.info("=" * 80)

    except Exception as error:
        logger.exception("Chunking failed: %s", error)
        sys.exit(1)


if __name__ == "__main__":
    main()