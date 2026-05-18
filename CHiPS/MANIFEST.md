# CHiPPY Project Manifest

## Complete Package Contents

### Root Level Files
```
CHiPPY/
├── README.md                 - Main overview and features
├── requirements.txt          - Complete dependency list
├── LICENSE.md               - Licensing information
├── .gitignore              - Git ignore patterns
└── docs/                   - Complete documentation
    ├── INDEX.md            - Documentation index and navigation
    ├── ARCHITECTURE.md     - Detailed system architecture
    ├── QUICKSTART.md       - 15-minute setup guide
    └── SETUP_INSTRUCTIONS.md - Deployment and operations guide
```

### Stage 1: Preprocessing (chips-rag)
```
01_preprocessing/
├── README.md               - Stage 1 detailed documentation
├── run_stage1.py          - Main entry point for preprocessing
├── run_stage2.py          - Enhanced OCR pipeline
├── diagnose_stage1.py     - Diagnostic tool
├── test_stage1.py         - Test suite
├── stage1_image_prep/     - Image preprocessing modules
│   ├── __init__.py
│   ├── config.py          - Image processing configuration
│   ├── pipeline.py        - Main preprocessing pipeline
│   ├── denoise.py         - Noise reduction
│   ├── deskew.py          - Text alignment correction
│   ├── pdf_to_image.py    - PDF to image conversion
│   ├── stamp_detector.py  - Overlay text removal
│   └── __pycache__/
├── stage2_ocr/            - OCR engine implementations
│   ├── __init__.py
│   ├── config.py          - OCR configuration
│   ├── pipeline.py        - OCR pipeline orchestration
│   ├── docling_ocr.py     - Docling backend
│   ├── models.py          - Model loading and selection
│   ├── postprocess.py     - OCR result post-processing
│   └── __pycache__/
├── input_pdfs/            - Input directory for PDFs
│   └── .gitkeep
├── stage1_output/         - First pass OCR results
├── stage2_output/         - Enhanced OCR results
├── stage1_diagnostics/    - Diagnostic outputs
└── used_files/            - Reference files
```

### Stage 2: Optimization
```
02_optimization/
├── optimize.py            - Text normalization and optimization
├── spellv2.py            - Spell checking and correction
└── dict/                 - Dictionary resources
    ├── hi_dict_2_updated.txt - Main dictionary
    └── office.txt             - Office/business terms dictionary
```

### Stage 3: Chunking
```
03_chunking/
└── docling_chunker.py    - Intelligent document chunking
```

### Stage 4: Embeddings & Knowledge Graphs
```
04_embeddings_and_kg/
└── scripts/              - All embedding and KG scripts
    ├── embeddings.py              - Vector embedding generation
    ├── build_knowledge_graph.py   - KG construction
    ├── knowledge_graph.py         - KG data structures
    ├── kg_retriever.py            - KG-based retrieval
    ├── entity_extraction.py       - Named entity recognition
    ├── integrated_retrieval.py    - Combined search layer
    ├── rag_pipeline.py            - RAG with Ollama support
    ├── kg_config.py               - KG configuration
    ├── quickstart.py              - Quick start script
    ├── data_input.py              - Data input handling
    ├── config.py                  - General configuration
    ├── f1.py                      - F1 scoring utilities
    ├── test_*.py                  - Test suite files
    ├── *README.md                 - Documentation files
    ├── *GUIDE.md                  - Setup and usage guides
    ├── knowledge_graph.json       - Serialized KG (generated)
    ├── requirements_kg.txt        - KG-specific requirements
    └── __pycache__/
├── data/                  - Input data and cache
│   └── .gitkeep
└── db/                   - Vector database storage
    └── .gitkeep
```

### Stage 5: Web UI
```
05_webui/
├── app.py                             - Flask web application
├── static/                            - Frontend assets
│   ├── style.css                      - Web UI styling
│   └── script.js                      - Client-side logic
└── templates/                         - HTML templates
    └── index.html                     - Query interface
```

### Documentation
```
docs/
├── INDEX.md                    - Doc navigation and overview
├── ARCHITECTURE.md             - Complete system architecture
├── QUICKSTART.md              - Installation and first steps
└── SETUP_INSTRUCTIONS.md      - Deployment and operations
```

## File Size Estimation

| Component | Files | Size |
|-----------|-------|------|
| Core Code | 40+ | ~1.5 MB |
| Documentation | 6 | ~500 KB |
| Dependencies (venv) | 1000s | ~3-5 GB |
| Data/Models (runtime) | - | ~2-3 GB |
| Total Initial | - | ~1.5 MB |
| Total with Environment | - | ~5-8 GB |

## Technology Stack

### Languages & Frameworks
- **Python 3.9+** - Primary language
- **Flask/FastAPI** - Web framework
- **Docker** - Containerization (optional)

### Core Libraries

**Image & PDF Processing**
- PyMuPDF, OpenCV, Pillow, scikit-image

**OCR**
- Tesseract, EasyOCR, RapidOCR

**NLP**
- spaCy, NLTK, textacy

**Embeddings & Vector DB**
- FlagEmbedding, sentence-transformers, Qdrant

**Knowledge Graphs**
- NetworkX, spaCy (entity extraction)

**Web**
- Flask, Flask-CORS, FastAPI (optional)

**Data Processing**
- NumPy, Pandas, SciPy

## Pipeline Flow Diagram

```
User PDFs
    ↓
[01] PREPROCESSING
     Extract text via OCR
    ↓
[02] OPTIMIZATION
     Clean and normalize text
    ↓
[03] CHUNKING
     Split into semantic chunks
    ↓
[04] EMBEDDINGS & KG
     Generate vectors and relationships
    ↓
[05] WEB UI
     Query interface with Ollama
    ↓
User Results
```

## Configuration & Customization Points

1. **Stage 1 Image Processing**: `01_preprocessing/stage1_image_prep/config.py`
2. **Stage 1 OCR**: `01_preprocessing/stage2_ocr/config.py`
3. **Stage 2 Optimization**: `02_optimization/optimize.py`, `spellv2.py`
4. **Stage 4 Embeddings**: `04_embeddings_and_kg/scripts/kg_config.py`
5. **Stage 5 Web UI**: `05_webui/app.py`

## Data Flow Paths

```
Input PDFs
  ↓
  01_preprocessing/input_pdfs/
  ↓
  Process → 01_preprocessing/stage1_output/
  ↓
  Process → 01_preprocessing/stage2_output/
  ↓
  Process → 02_optimization/output/
  ↓
  Process → 03_chunking/output/
  ↓
  Process → 04_embeddings_and_kg/data/
            04_embeddings_and_kg/db/
  ↓
  Serve via 05_webui/ on localhost:5000
```

## Usage Summary

### Installation
```bash
cd CHiPPY
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### Basic Usage
```bash
# Full pipeline execution
cd 01_preprocessing && python run_stage1.py && python run_stage2.py && cd ..
cd 02_optimization && python optimize.py && python spellv2.py && cd ..
cd 03_chunking && python docling_chunker.py && cd ..
cd 04_embeddings_and_kg/scripts && python build_knowledge_graph.py && python embeddings.py && cd ../..
cd 05_webui && python app.py
# Access: http://localhost:5000
```

### Individual Stage Usage
```bash
# Just preprocessing
cd 01_preprocessing && python run_stage1.py

# Query system (with Ollama)
cd 04_embeddings_and_kg/scripts && python rag_pipeline.py

# Web interface
cd 05_webui && python app.py
```

## Key Features

✅ Multi-stage document processing pipeline
✅ Multiple OCR backends (Tesseract, EasyOCR, RapidOCR)
✅ Intelligent text chunking with metadata preservation
✅ Advanced knowledge graph construction
✅ Vector embedding generation and storage
✅ Web-based query interface
✅ Ollama LLM integration
✅ Hybrid search capabilities (vector + keyword)
✅ Production-ready error handling
✅ Extensible modular architecture

## Documentation Structure

- **README.md** - Start here for overview
- **docs/QUICKSTART.md** - 15-minute setup
- **docs/ARCHITECTURE.md** - Technical deep dive
- **docs/SETUP_INSTRUCTIONS.md** - Deployment options
- **docs/INDEX.md** - Complete navigation
- **01_preprocessing/README.md** - Stage-specific guide

## License & Attribution

- **License**: MIT (pipeline integration)
- **Components**: See LICENSE.md and individual file headers
- **Third-party**: See requirements.txt for dependencies and their licenses

## Support & Resources

1. Check documentation in `docs/` folder
2. Review configuration files (all commented)
3. Check stage-specific README files
4. Run diagnostic/test files as needed

## Version Information

- **Version**: 1.0 (Production Ready)
- **Release Date**: March 2026
- **Python**: 3.9+
- **Status**: Stable

## Next Steps

1. Read [README.md](README.md) for overview
2. Follow [QUICKSTART.md](docs/QUICKSTART.md) for setup
3. Review [ARCHITECTURE.md](docs/ARCHITECTURE.md) for technical details
4. Configure and customize as needed
5. Run pipeline on your documents

---

**Total Package**: Complete RAG pipeline ready for development, testing, and production deployment.

**Estimated Setup Time**: ~15-30 minutes
**Estimated First Document Processing**: ~5-10 minutes (depending on complexity)
