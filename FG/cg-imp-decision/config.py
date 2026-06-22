from pathlib import Path


ROOT = Path(__file__).resolve().parent
PDF_PATH = ROOT / "Imp_Dicisions_CGSIC.pdf"
ARTIFACTS_DIR = ROOT / "artifacts"
WORK_DIR = ROOT / "work"

MANIFEST_PATH = ARTIFACTS_DIR / "decision_manifest.json"
PAGE_TEXT_DIR = ARTIFACTS_DIR / "page_text"
DECISIONS_DIR = ARTIFACTS_DIR / "decisions"
DECISION_PDF_DIR = DECISIONS_DIR / "pdf"
DECISION_TEXT_DIR = DECISIONS_DIR / "text"
CHUNKS_DIR = ARTIFACTS_DIR / "chunks"
CHUNKS_PATH = CHUNKS_DIR / "cgsic_legal_chunks.jsonl"
INDEX_MANIFEST_PATH = ARTIFACTS_DIR / "index_manifest.json"

SOURCE_DOCUMENT_ID = "CGSIC_IMPORTANT_DECISIONS_2022"
SOURCE_TYPE = "CGSIC_DECISION_COMPILATION"
CORPUS = "CGSIC_IMPORTANT_DECISIONS_2022"
COMMISSION = "CG_SIC"
JURISDICTION = "CHHATTISGARH"

PHYSICAL_PAGE_COUNT = 454
FRONT_MATTER_END = 7
TOC_PAGE_START = 8
TOC_PAGE_END = 16
BODY_PAGE_START = 18
BODY_PAGE_END = 453
BACK_COVER_PAGE = 454
PRINTED_PAGE_OFFSET = 17

COLLECTION_NAME = "cgsic_important_decisions_v1"
VECTOR_SIZE = 1024

# Verified from the printed contents table on physical PDF pages 8-16.
# The list position is the TOC sequence number (1-based); the value is the
# printed start page. Entries 125 and 126 are intentionally out of page order
# in the source contents table.
PRINTED_START_PAGES = [
    1, 2, 4, 6, 11, 14, 18, 23, 33, 37, 39, 43, 46, 49, 51, 53,
    59, 68, 70, 76, 78, 80, 83, 88, 92, 94, 99, 105, 109,
    112, 114, 120, 123, 127, 130, 133, 136, 139, 141, 143, 147,
    149, 151, 154, 157, 159, 163,
    165, 168, 172, 175, 178, 181, 184, 188, 193, 197, 199, 201,
    205, 208, 210, 213, 214,
    215, 216, 218, 221, 223, 225, 227, 229, 231, 235, 251, 255,
    256, 257, 258, 260,
    262, 264, 266, 268, 270, 275, 277, 282, 283, 286, 288, 295,
    299, 303, 310, 314, 316, 320, 324,
    328, 330, 334, 338, 341, 344, 347, 349, 352, 354, 356, 360,
    362, 363, 365, 369,
    371, 373, 375, 378, 381, 384, 387, 389, 391, 397, 395, 399,
    403,
    409, 412, 414, 416, 419, 421, 424, 430,
]

