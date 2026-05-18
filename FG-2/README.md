# CHiPPY - Complete High-Performance Pipeline

A comprehensive, production-ready RAG (Retrieval-Augmented Generation) pipeline that processes documents through multiple stages of preprocessing, optimization, chunking, embedding, and knowledge graph construction.

## Overview

CHiPPY is a complete document processing pipeline designed for:
- **Document Preprocessing**: PDF processing with OCR using CHIPS-RAG
- **Text Optimization**: Spell checking and text normalization
- **Intelligent Chunking**: Document segmentation using Docling
- **Embeddings & Knowledge Graphs**: Vector embeddings and entity relationship mapping
- **Interactive Web UI**: Local web interface for queries and result exploration

## Pipeline Architecture

```
INPUT DOCUMENTS
        ↓
[01] PREPROCESSING (chips-rag)
     - PDF to image conversion
     - Image enhancement & deskewing
     - OCR with multiple backends
        ↓
[02] OPTIMIZATION
     - Text spell checking (spellv2.py)
     - Text normalization (optimize.py)
     - Dictionary-based corrections
        ↓
[03] CHUNKING
     - Intelligent document segmentation
     - Metadata preservation (docling)
        ↓
[04] EMBEDDINGS & KNOWLEDGE GRAPHS
     - Generate vector embeddings
     - Build knowledge graphs
     - Entity extraction and linking
        ↓
[05] WEB UI
     - Query interface
     - Result retrieval (with Ollama)
     - Knowledge graph visualization
```

## Quick Start

### Prerequisites
- Python 3.9+
- pip or conda
- For full functionality: Ollama (optional, for LLM integration)

### Installation

1. **Clone/Setup the repository**
   ```bash
   cd CHiPPY
   pip install -r requirements.txt
   ```

2. **Download spaCy model** (required for NLP)
   ```bash
   python -m spacy download en_core_web_sm
   ```

3. **Prepare input documents**
   - Place PDF files in `01_preprocessing/input_pdfs/`

### Running the Pipeline

**Full Pipeline** (Sequential execution):
```bash
# Stage 1: Preprocessing
cd 01_preprocessing
python run_stage1.py

# Stage 2: Detailed OCR
python run_stage2.py

# Stage 3: Optimization
cd ../02_optimization
python optimize.py
python spellv2.py

# Stage 4: Chunking
cd ../03_chunking
python docling_chunker.py

# Stage 5: Embeddings & KG
cd ../04_embeddings_and_kg/scripts
python build_knowledge_graph.py
python embeddings.py

# Stage 6: Start Web UI
cd ../../05_webui
python app.py
# Navigate to http://localhost:5000
```

**Individual Stages**:
Each stage can be run independently. Refer to stage-specific documentation in the ARCHITECTURE.md file.

## Directory Structure

```
CHiPPY/
├── 01_preprocessing/          # PDF processing & OCR
│   ├── run_stage1.py         # Entry point for preprocessing
│   ├── run_stage2.py         # Second OCR pass
│   ├── stage1_image_prep/    # Image preprocessing modules
│   ├── stage2_ocr/           # OCR engine implementations
│   └── input_pdfs/           # Input directory
├── 02_optimization/          # Text refinement
│   ├── optimize.py          # Text optimization
│   ├── spellv2.py           # Spell checking
│   └── dict/                # Dictionary files
├── 03_chunking/             # Document segmentation
│   └── docling_chunker.py   # Intelligent chunking
├── 04_embeddings_and_kg/    # Vector embeddings & KG
│   ├── scripts/             # All KG building and retrieval scripts
│   ├── data/                # Input data directory
│   └── db/                  # Vector database storage
├── 05_webui/                # Web interface
│   ├── app.py              # Flask/web application
│   ├── static/             # Frontend assets
│   └── templates/          # HTML templates
└── docs/                    # Documentation

```

## Configuration

Each stage has its own configuration file:
- `01_preprocessing/stage1_image_prep/config.py` - Image processing settings
- `01_preprocessing/stage2_ocr/config.py` - OCR options
- `04_embeddings_and_kg/scripts/kg_config.py` - Knowledge graph settings

See ARCHITECTURE.md for detailed configuration options.

## Dependencies

Key dependencies:
- **Image Processing**: OpenCV, PyMuPDF
- **OCR**: Tesseract, EasyOCR, RapidOCR
- **NLP**: spaCy, NLTK
- **Embeddings**: FlagEmbedding (BGE)
- **Database**: Qdrant (for vector storage)
- **Graph**: NetworkX
- **Web**: Flask or FastAPI
- **LLM Integration**: Ollama (optional)

Full requirements available in [requirements.txt](requirements.txt)

## Usage Examples

### Example 1: Basic Document Processing
```python
# In 01_preprocessing/
python run_stage1.py --input-dir input_pdfs --output-dir stage1_output
python run_stage2.py --input-dir stage1_output --output-dir stage2_output
```

### Example 2: Query the System (with Ollama)
```python
# In 04_embeddings_and_kg/scripts/
python rag_pipeline.py --query "What is mentioned about X?" --model ollama
```

### Example 3: Access via Web UI
```
1. Start app: python 05_webui/app.py
2. Open: http://localhost:5000
3. Upload documents or enter queries
```

## Key Features

✅ **Multi-stage OCR**: Multiple OCR backends for robustness
✅ **Intelligent Chunking**: Preserves document structure
✅ **Knowledge Graphs**: Entity relationships and context
✅ **Hybrid Search**: Vector + sparse search capabilities
✅ **Production Ready**: Comprehensive error handling and logging
✅ **Extensible**: Modular architecture for custom implementations
✅ **Web Interface**: Intuitive UI for end users

## Troubleshooting

**OCR Issues**: Refer to `01_preprocessing/` documentation
**Chunking Problems**: Check `03_chunking/` for chunking guidelines
**KG Build Failures**: See `04_embeddings_and_kg/scripts/SETUP_GUIDE.md`
**Web UI Errors**: Verify Flask/dependencies in `requirements.txt`

## Documentation

- [ARCHITECTURE.md](docs/ARCHITECTURE.md) - Detailed system architecture
- [QUICKSTART.md](docs/QUICKSTART.md) - Step-by-step setup guide
- Individual stage documentation in respective directories

## Performance Notes

- **Preprocessing**: ~30-60 seconds per 100-page PDF
- **OCR**: ~5-15 minutes for 100 pages (depending on image quality)
- **Chunking**: ~1-2 minutes for 100,000 tokens
- **KG Building**: ~2-5 minutes for 100 chunks
- **Queries**: <500ms (with pre-built indices)

## Contributing

When modifying stages:
1. Update corresponding config files
2. Add tests in stage directories
3. Update documentation
4. Run full pipeline for validation

## License

See LICENSE file in respective source directories

## Support

For issues or questions:
1. Check stage-specific README files
2. Review configuration guidelines
3. Check individual module documentation files

---

**Latest Update**: March 2026  
**Version**: 1.0 (Production)
