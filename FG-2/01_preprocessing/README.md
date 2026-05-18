# Stage 1: Preprocessing - PDF to Text Extraction

## Overview

Stage 1 converts PDF documents into searchable text using multi-stage image processing and multiple OCR backends. This is the foundation of the CHiPPY pipeline.

## Pipeline Architecture

```
PDF File
   ↓
PDF to Images (PDFtoImage.py)
   ↓
Image Preprocessing
   ├─ Denoise (denoise.py)
   ├─ Deskew (deskew.py)
   └─ Stamp Detection (stamp_detector.py)
   ↓
Multiple OCR Backends (in parallel or sequential)
   ├─ Tesseract OCR (tesseractcli)
   ├─ EasyOCR (easyocr)
   └─ RapidOCR (rapidocr)
   ↓
Text Output (stage1_output/)
   ↓ (Stage 2)
Enhanced OCR (run_stage2.py)
   ↓
Final OCR Output (stage2_output/)
```

## Quick Start

### 1. Place PDFs
```bash
# Copy or move PDF files to:
01_preprocessing/input_pdfs/
```

### 2. Run Stage 1
```bash
cd 01_preprocessing
python run_stage1.py
```

### 3. Check Output
```bash
# Results in:
01_preprocessing/stage1_output/{document_name}/

# View extracted text:
cat stage1_output/{document_name}/combined.txt
```

### 4. (Optional) Run Stage 2 for Enhanced OCR
```bash
python run_stage2.py
# Results in: 01_preprocessing/stage2_output/
```

## Configuration

### File: `stage1_image_prep/config.py`

```python
# Image Processing Settings
DPI = 200                           # Resolution (100-300)
BRIGHTNESS_THRESHOLD = 127         # For binary conversion
DENOISE_STRENGTH = 1.5             # 0.5-3.0, higher = more aggressive
DESKEW_CONFIDENCE = 0.7            # 0.5-1.0, higher = more strict

# Optional Preprocessing
ENABLE_DENOISE = True
ENABLE_DESKEW = True
ENABLE_STAMP_DETECTION = False     # Slows processing
```

### File: `stage2_ocr/config.py`

```python
# OCR Engine Selection
OCR_BACKEND = 'tesseract'          # 'tesseract', 'easyocr', 'rapidocr'

# Language & Model Settings
LANGUAGE = 'eng'                   # Language code
CONFIDENCE_THRESHOLD = 0.5         # 0.0-1.0, filters low-confidence results

# Performance
NUM_WORKERS = 2                    # Parallel processing threads
BATCH_SIZE = 10                    # Pages per batch
TIMEOUT_SEC = 30                   # Per page timeout
```

## Available OCR Backends

### Tesseract OCR
- **Pros**: Lightweight, fast, multilingual
- **Cons**: Lower accuracy on handwriting
- **Setup**: See installation notes

### EasyOCR
- **Pros**: High accuracy, supports many languages
- **Cons**: Slower, memory intensive
- **Best for**: High-quality documents, multiple languages

### RapidOCR
- **Pros**: Very fast, good accuracy
- **Cons**: Less mature
- **Best for**: Speed-critical applications

## Installation Requirements

### Windows
```powershell
# Install Tesseract
# Download: https://github.com/UB-Mannheim/tesseract/wiki
# Or use chocolatey:
choco install tesseract

# Python dependencies
pip install pytesseract easyocr rapidocr-onnxruntime
```

### macOS
```bash
# Install Tesseract
brew install tesseract

# Python dependencies
pip install pytesseract easyocr rapidocr-onnxruntime
```

### Linux (Ubuntu/Debian)
```bash
# Install Tesseract
sudo apt-get install tesseract-ocr

# Optional: additional language packs
sudo apt-get install tesseract-ocr-fra tesseract-ocr-deu

# Python dependencies
pip install pytesseract easyocr rapidocr-onnxruntime
```

## Usage Examples

### Example 1: Process Single PDF
```bash
python run_stage1.py --input "documents/report.pdf"
```

### Example 2: Process with Specific OCR Backend
```bash
# Modify config.py OCR_BACKEND first, then:
python run_stage1.py
```

### Example 3: High-Quality Processing
```python
# In config.py:
DPI = 300                    # High resolution
ENABLE_DENOISE = True        # Remove noise
ENABLE_DESKEW = True        # Fix alignment
ENABLE_STAMP_DETECTION = True  # Remove watermarks
OCR_BACKEND = 'easyocr'     # Best accuracy
```

### Example 4: Fast Processing
```python
# In config.py:
DPI = 100                    # Low resolution
ENABLE_DENOISE = False       # Skip preprocessing
ENABLE_DESKEW = False
OCR_BACKEND = 'rapidocr'    # Fastest
```

## Output Structure

```
stage1_output/
├── report/
│   ├── page_01.txt         # Page 1 OCR
│   ├── page_02.txt         # Page 2 OCR
│   ├── page_03.txt         # Page 3 OCR
│   └── combined.txt        # All pages combined
├── proposal/
│   ├── page_01.txt
│   ├── ...
│   └── combined.txt
└── ...

stage2_output/
├── report/
│   └── combined.txt        # Stage 2 enhanced OCR
├── proposal/
│   └── combined.txt
└── ...
```

## Performance Metrics

| Setting | Time (100 pages) | Quality | Memory |
|---------|------------------|---------|--------|
| Fast (DPI=100, Tesseract) | 30s | Standard | 1 GB |
| Balanced (DPI=150, EasyOCR) | 90s | High | 3 GB |
| High-Quality (DPI=300, EasyOCR) | 180s | Very High | 5 GB |

## Troubleshooting

### Error: "tesseract is not installed or it's not in your PATH"

**Windows**:
1. Install from: https://github.com/UB-Mannheim/tesseract/wiki
2. Add to PATH: `C:\Program Files\Tesseract-OCR`
3. Or specify in code:
```python
import pytesseract
pytesseract.pytesseract.pytesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
```

**macOS/Linux**:
```bash
# Check if installed
which tesseract

# If not, install
brew install tesseract  # macOS
sudo apt-get install tesseract-ocr  # Linux
```

### Error: "PDF has no pages"
- Ensure PDF is valid (try opening in Reader)
- Check file permissions
- Verify file isn't corrupted

### Error: "CUDA out of memory" (EasyOCR)
- Reduce batch size in config
- Use CPU instead: set in easyocr call
- Process fewer pages at once

### Poor OCR Quality
1. Try different OCR backend
2. Increase DPI in config
3. Enable denoise and deskew
4. Check PDF has text (not scanned image)

### Slow Processing
1. Reduce DPI to 100-150
2. Switch to RapidOCR
3. Disable unnecessary preprocessing
4. Increase NUM_WORKERS

## Advanced Configuration

### Multi-Language Support

```python
# In stage2_ocr/config.py
LANGUAGE = ['eng', 'fra', 'deu']  # English, French, German

# Or for EasyOCR:
easyocr.Reader(['en', 'fr', 'de'])
```

### Batch Processing

```bash
# Process entire directory
for pdf in input_pdfs/*.pdf; do
    python run_stage1.py --input "$pdf"
done
```

### Custom Preprocessing

Extend `denoise.py` or `deskew.py` for custom filters:

```python
# In stage1_image_prep/pipeline.py
def custom_preprocess(image):
    # Your custom preprocessing
    return processed_image
```

## Integration with Next Stage

Output from Stage 1 is consumed by [Stage 2: Optimization](../02_optimization/README.md)

The `combined.txt` file from each document folder is the input to:
```bash
cd ../02_optimization
python optimize.py
```

## Quality Assessment

### Check OCR Quality
```bash
# View first 100 characters of OCR output
head -c 100 stage1_output/{document}/combined.txt
```

### Validate Completeness
```bash
# Count words extracted
wc -w stage1_output/{document}/combined.txt
```

### Debug Specific Pages
```bash
# View specific page OCR
cat stage1_output/{document}/page_05.txt
```

## Dependencies

Core dependencies for Stage 1:
- PyMuPDF - PDF processing
- opencv-python - Image processing
- pytesseract - Tesseract wrapper
- easyocr - EasyOCR wrapper
- rapidocr-onnxruntime - RapidOCR

See [requirements.txt](../requirements.txt) for complete list.

## Tips & Best Practices

✅ **DO**:
- Use DPI 150-200 for most documents
- Enable denoise for scanned PDFs
- Save processed PDFs, they're reusable
- Monitor output quality on first few pages

❌ **DON'T**:
- Use DPI >300 unless necessary (slow)
- Enable all preprocessing (slower performance)
- Mix OCR backends per document (inconsistent)
- Process corrupted PDFs (will fail)

## Next Steps

1. Configure settings in `stage1_image_prep/config.py`
2. Place PDFs in `input_pdfs/`
3. Run `run_stage1.py`
4. Verify output in `stage1_output/`
5. (Optional) Run Stage 2 with `run_stage2.py`
6. Continue to [Stage 2: Text Optimization](../02_optimization/README.md)

---

**For more information**, see:
- [Main Architecture](../../docs/ARCHITECTURE.md)
- [Full Documentation Index](../../docs/INDEX.md)
