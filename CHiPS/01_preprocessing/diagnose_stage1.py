"""Diagnostic: compare original PDF renders vs Stage 1 output to detect info loss.

For each page:
1. Render original PDF page at 300 DPI (ground truth)
2. Load the Stage 1 processed output
3. Compare: find regions where content exists in original but is missing in output
4. Report any significant differences (potential text loss)
"""

import cv2
import numpy as np
import json
from pathlib import Path

# Paths
PDF_PATH = Path("input_pdfs/letter 376 date 18-6-24 agenda letter.pdf")
OUTPUT_DIR = Path("stage1_output/letter 376 date 18-6-24 agenda letter")
DIAG_DIR = Path("stage1_diagnostics")
DIAG_DIR.mkdir(exist_ok=True)

# Render original pages
from stage1_image_prep.pdf_to_image import pdf_to_images

print("=" * 60)
print("STAGE 1 OUTPUT DIAGNOSTIC — Information Loss Check")
print("=" * 60)

originals = pdf_to_images(PDF_PATH)
print(f"\nPDF: {PDF_PATH.name}")
print(f"Pages: {len(originals)}")
print()

issues_found = 0

for page_num in range(len(originals)):
    original = originals[page_num]
    output_path = OUTPUT_DIR / f"page_{page_num:04d}.png"

    if not output_path.exists():
        print(f"Page {page_num}: OUTPUT FILE MISSING — {output_path}")
        issues_found += 1
        continue

    processed = cv2.imread(str(output_path))

    # --- Size check ---
    if original.shape != processed.shape:
        print(f"Page {page_num}: SIZE MISMATCH — original {original.shape} vs processed {processed.shape}")
        # Resize for comparison
        processed = cv2.resize(processed, (original.shape[1], original.shape[0]))

    # --- Convert both to grayscale for comparison ---
    orig_gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    proc_gray = cv2.cvtColor(processed, cv2.COLOR_BGR2GRAY)

    # --- Binarize both (text = black pixels) ---
    _, orig_bin = cv2.threshold(orig_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    _, proc_bin = cv2.threshold(proc_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # --- Find content in original that's MISSING from processed ---
    # Where original has text (255) but processed doesn't (0) → lost content
    lost_mask = cv2.bitwise_and(orig_bin, cv2.bitwise_not(proc_bin))

    # --- Find content in processed that's NEW (not in original) → artifacts ---
    added_mask = cv2.bitwise_and(proc_bin, cv2.bitwise_not(orig_bin))

    # --- Analyze lost content ---
    # Group lost pixels into connected components to find lost "objects"
    num_lost, lost_labels, lost_stats, _ = cv2.connectedComponentsWithStats(lost_mask, connectivity=8)
    
    lost_small = 0  # tiny dots (< 20px) — probably just speckles, fine to lose
    lost_medium = 0  # medium (20-200px) — could be punctuation, matras
    lost_large = 0  # large (> 200px) — likely text characters or headings
    lost_large_regions = []

    for label in range(1, num_lost):
        area = lost_stats[label, cv2.CC_STAT_AREA]
        if area < 20:
            lost_small += 1
        elif area < 200:
            lost_medium += 1
        else:
            lost_large += 1
            x = lost_stats[label, cv2.CC_STAT_LEFT]
            y = lost_stats[label, cv2.CC_STAT_TOP]
            w = lost_stats[label, cv2.CC_STAT_WIDTH]
            h = lost_stats[label, cv2.CC_STAT_HEIGHT]
            lost_large_regions.append((x, y, w, h, area))

    # --- Statistics ---
    orig_text_pixels = np.count_nonzero(orig_bin)
    proc_text_pixels = np.count_nonzero(proc_bin)
    lost_pixels = np.count_nonzero(lost_mask)
    added_pixels = np.count_nonzero(added_mask)
    
    retention_pct = (1 - lost_pixels / max(orig_text_pixels, 1)) * 100

    # --- Analyze top/middle/bottom thirds for structural loss ---
    h_img = orig_gray.shape[0]
    third = h_img // 3
    lost_top = np.count_nonzero(lost_mask[:third, :])
    lost_mid = np.count_nonzero(lost_mask[third:2*third, :])
    lost_bot = np.count_nonzero(lost_mask[2*third:, :])

    # --- Print Report ---
    status = "OK" if lost_large == 0 and retention_pct > 98 else "WARNING" if retention_pct > 95 else "PROBLEM"
    if status != "OK":
        issues_found += 1

    print(f"Page {page_num} [{status}]")
    print(f"  Text retention: {retention_pct:.2f}%")
    print(f"  Original text pixels: {orig_text_pixels:,} | Processed: {proc_text_pixels:,}")
    print(f"  Lost components: {lost_small} tiny (<20px), {lost_medium} medium (20-200px), {lost_large} LARGE (>200px)")
    if lost_large > 0:
        print(f"  *** LARGE CONTENT LOSS DETECTED ***")
        for i, (x, y, w, h, area) in enumerate(lost_large_regions):
            region_desc = "TOP (heading area)" if y < third else "MIDDLE (body)" if y < 2*third else "BOTTOM (footer)"
            print(f"    Region {i+1}: {region_desc} at ({x},{y}) size {w}x{h} = {area}px")
    print(f"  Loss by region: top={lost_top:,}px, middle={lost_mid:,}px, bottom={lost_bot:,}px")
    print(f"  Added pixels (artifacts): {added_pixels:,}")

    # --- Save diagnostic image: red = lost content, green = added ---
    diag_image = original.copy()
    diag_image[lost_mask == 255] = (0, 0, 255)  # Red = lost
    diag_image[added_mask == 255] = (0, 255, 0)  # Green = added

    # Draw rectangles around large lost regions
    for (x, y, w, h, area) in lost_large_regions:
        cv2.rectangle(diag_image, (x, y), (x+w, y+h), (0, 0, 255), 3)
        cv2.putText(diag_image, f"LOST {area}px", (x, y-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

    cv2.imwrite(str(DIAG_DIR / f"page_{page_num:04d}_diff.png"), diag_image)
    print()

# --- Load and show metadata ---
meta_path = OUTPUT_DIR / "metadata.json"
with open(meta_path, "r", encoding="utf-8") as f:
    meta = json.load(f)

print("=" * 60)
print("METADATA SUMMARY")
print("=" * 60)
for p in meta["pages"]:
    flags = []
    if p["skew_angle"] != 0:
        flags.append(f"deskewed {p['skew_angle']}°")
    if p["has_stamps"]:
        flags.append(f"{p['stamp_count']} stamps")
    if p["has_handwriting"]:
        flags.append("handwriting")
    flags_str = ", ".join(flags) if flags else "clean"
    print(f"  Page {p['page_num']}: speckles={p['noise_stats']['speckles_removed']}, {flags_str}")

print()
print("=" * 60)
if issues_found == 0:
    print("RESULT: All pages look good for OCR — no significant content loss.")
else:
    print(f"RESULT: {issues_found} page(s) have potential issues — check diagnostic images.")
print(f"Diagnostic images saved to: {DIAG_DIR.resolve()}")
print("  Red pixels = content in original but missing in output")
print("  Green pixels = content in output but not in original")
print("  Red rectangles = large lost regions (potential text loss)")
