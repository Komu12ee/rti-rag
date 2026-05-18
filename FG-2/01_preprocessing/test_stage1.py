"""Quick test: generate a tiny PDF with text and run Stage 1 on it."""
import fitz  # PyMuPDF
from pathlib import Path

# --- Create a test PDF ---
test_pdf = Path("input_pdfs/test_sample.pdf")
doc = fitz.open()

# Page 1: English text
page = doc.new_page(width=595, height=842)  # A4
page.insert_text((72, 100), "Government of Chhattisgarh", fontsize=18)
page.insert_text((72, 140), "Department of Information Technology", fontsize=14)
page.insert_text((72, 200), "Meeting Agenda - CHIPS Department", fontsize=12)
page.insert_text((72, 240), "Date: 15th January 2025", fontsize=11)
page.insert_text((72, 280), "1. Review of ongoing projects", fontsize=11)
page.insert_text((72, 310), "2. Budget allocation for Q3", fontsize=11)
page.insert_text((72, 340), "3. Status of digitization drive", fontsize=11)

# Page 2: More text
page2 = doc.new_page(width=595, height=842)
page2.insert_text((72, 100), "Project Report - Digital Infrastructure", fontsize=16)
page2.insert_text((72, 160), "This document outlines the progress of", fontsize=11)
page2.insert_text((72, 190), "the state-wide digital infrastructure project.", fontsize=11)
page2.insert_text((72, 250), "Total Budget: Rs. 45,00,000", fontsize=11)
page2.insert_text((72, 280), "Spent: Rs. 28,50,000", fontsize=11)
page2.insert_text((72, 310), "Remaining: Rs. 16,50,000", fontsize=11)

doc.save(str(test_pdf))
doc.close()
print(f"Test PDF created: {test_pdf.resolve()}")
print(f"Pages: 2")

# --- Run Stage 1 pipeline ---
print("\n--- Running Stage 1 Pipeline ---\n")
from stage1_image_prep import ImagePrepPipeline

pipeline = ImagePrepPipeline(output_dir="stage1_output", save_debug_images=True)
result = pipeline.process(test_pdf)

print(f"\n--- Results ---")
print(f"PDF: {result.pdf_path}")
print(f"Total pages: {result.total_pages}")
for p in result.pages:
    print(f"  Page {p.page_num}: skew={p.skew_angle}°, "
          f"speckles_removed={p.noise_stats.get('speckles_removed', 0)}, "
          f"stamps={p.stamp_count}, saved={p.image_path}")

print(f"\nOutput saved to: {Path('stage1_output').resolve()}")
