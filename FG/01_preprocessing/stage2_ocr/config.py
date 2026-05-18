"""Configuration for Stage 2 — OCR and Structure Extraction."""

from pathlib import Path

# ---------- Docling ----------
# OCR engine to use within Docling. Options:
#   "easyocr"    — good Hindi support, runs on CPU/GPU
#   "rapidocr"   — bundled with Docling, lighter weight
#   "tesseract"  — requires system install, decent Hindi
OCR_ENGINE = "easyocr"

# Languages for OCR. EasyOCR language codes.
OCR_LANGUAGES = ["hi", "en"]

# Force OCR on the entire page. Required because our inputs are images
# (no embedded text layer), so Docling must OCR everything.
FORCE_FULL_PAGE_OCR = True

# Minimum OCR confidence to keep a text box (0.0–1.0).
# Default Docling is 0.5 which drops too much Hindi text from scanned docs.
# Lowered to 0.05 to keep almost everything — post-processing cleans up noise.
OCR_CONFIDENCE_THRESHOLD = 0.05

# Max pixels (width * height) before downscaling for OCR.
# 6M pixels (~240 DPI A4) balances quality vs memory on 16 GB RAM machines.
OCR_MAX_PIXELS = 6_000_000

# ---------- Table Extraction ----------
ENABLE_TABLE_STRUCTURE = True

# ---------- Output ----------
DEFAULT_OUTPUT_DIR = Path("stage2_output")
OUTPUT_FORMATS = ["json", "md"]

# ---------- Confidence ----------
PAGE_CONFIDENCE_THRESHOLD = 0.6

# ---------- Sarvam OCR Fallback ----------
SARVAM_OCR_THRESHOLD = 0.6
