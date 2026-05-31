import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR.parent / 'FG' / '01_preprocessing'))

from docling.document_converter import DocumentConverter

converter = DocumentConverter()
sample_pdf = SCRIPT_DIR.parent / "FG" / "01_preprocessing" / "used_files" / "1_2025.pdf"

if not sample_pdf.exists():
    print(f"Sample PDF {sample_pdf} not found.")
    sys.exit(1)

print(f"Converting {sample_pdf}...")
result = converter.convert(str(sample_pdf))

print(f"Result type: {type(result)}")

if hasattr(result, 'pages') and result.pages:
    page = result.pages[0]
    print(f"Page class: {type(page)}")
    
    # 1. Inspect Cells
    cells = getattr(page, 'cells', [])
    print(f"Number of cells: {len(cells)}")
    
    ocr_confidences = []
    all_confidences = []
    for cell in cells:
        conf = getattr(cell, 'confidence', None)
        from_ocr = getattr(cell, 'from_ocr', False)
        if conf is not None:
            all_confidences.append(conf)
            if from_ocr:
                ocr_confidences.append(conf)
                
    if all_confidences:
        print(f"Average of all cell confidences: {sum(all_confidences) / len(all_confidences):.4f}")
    if ocr_confidences:
        print(f"Average of OCR cell confidences: {sum(ocr_confidences) / len(ocr_confidences):.4f}")
        print(f"Sample OCR confidences (first 10): {ocr_confidences[:10]}")
    
    # 3. Test the actual updated fallback function from docling_ocr
    try:
        from stage2_ocr.docling_ocr import _get_page_ocr_confidence
        score = _get_page_ocr_confidence(result, 1)
        print(f"--> Calculated page OCR confidence fallback result: {score}")
    except Exception as e:
        print(f"Failed to run _get_page_ocr_confidence: {e}")


