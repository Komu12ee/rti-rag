# The Ultimate Beginner's Guide: CHiPPY Advanced RAG Pipeline (Stages 1-5)

Welcome to the **CHiPPY RAG Pipeline**. This repository contains a production-ready, highly modular Retrieval-Augmented Generation (RAG) system specialized in extracting, cleaning, indexing, and querying complex scanned government and organizational documents (Hindi/English).

This guide walks you through the entire architecture, explaining the flow step-by-step, detailing the exact role of **every single `.py` file**, and providing a quick-start sequence for beginners.

---

## 1. Unified Pipeline Architecture

```
                       [ INPUT PDFS ]
                             │
  Stage 1: Preprocessing     │ (run_stage1.py)
                             ▼
                    [ CLEANED PNG IMAGES ]
                             │
  Stage 2: OCR Extraction    │ (run_stage2.py) -> (docling_ocr.py)
                             ▼
                    [ RAW MARKDOWN TEXT ]
                             │
  Stage 2.5: Optimization    │ (optimize.py) -> (spellv2.py)
                             ▼
                  [ OPTIMIZED MD & JSON ]
                             │
  Stage 3: Chunking          │ (chunk_stage2_output.py)
                             ▼
                   [ SEMANTIC TXT CHUNKS ]
                             │
  Stage 4: Indexing          │ (embeddings_production.py)
                             ▼
                   [ QDRANT VECTOR STORE ]
                             │
  Stage 4.5: RAG Queries     ├─► parent-child RAG (rag_pipeline_parent_child.py)
                             └─► multi-query + KG RAG (rag_pipeline.py)
                                           │
  Stage 5: Web UI Application              ▼ (app.py)
                              [ FLASK FRONTEND ]
```

---

## 2. Step-by-Step Flow: How Data Moves Through the Pipeline

### Step 1: Preprocessing & OCR (`01_preprocessing/`)
- Scanned PDF documents are placed into the `input_pdfs/` folder.
- **Stage 1** converts each PDF page into high-resolution PNG images. It runs denoising and deskewing to align text properly for the OCR engine.
- **Stage 2** processes these images through **Docling** (which uses a local **EasyOCR** engine configured for Hindi/English under the hood).
- If Docling's page-level OCR confidence score falls below a threshold, the pipeline automatically skips or triggers fallback handlers.
- **Output**: Generates a unified `structured.md` and `structured.json` for each document, separating page boundaries and preserving tables.

### Step 2: Text Optimization & Spelling Correction (`02_optimization/`)
- OCR text extracted from scanned pages often contains artifacts (e.g. stray dots, page numbers, duplicate lines, or list counters out of order).
- **Stage 2.5** cleans and optimizes the Markdown text. It joins hyphenated broken words, normalizes bullet points, collapses blank space, and cleans tables.
- It then executes a **SymSpell Hindi spell-correction** engine using a custom frequency dictionary. Devanagari words are analyzed, corrected for spelling mistakes, and frequencies are boosted in the dictionary to improve future accuracy.
- **Output**: Cleaned and spell-corrected Markdown documents stored under the optimization output folder.

### Step 3: Semantic Chunking (`03_chunking/`)
- Raw text cannot be fed directly to the database or LLM. It must be broken into digestible segments called "chunks."
- **Stage 3** uses Docling's **`HybridChunker`** and a tokenizer (such as `BAAI/bge-m3`) to divide the optimized Markdown document into semantic chunks of up to 1024 tokens.
- It is structure-aware—it avoids breaking apart tables, list items, or sentences. It also maps each text chunk back to the exact page number of the source document using `<!-- Page X -->` markers.
- **Output**: Individual numbered `.txt` chunk files containing structured metadata (original document name, page numbers, token count, and active structural headings).

### Step 4: Embeddings Indexing & Advanced RAG Queries (`04_embeddings_and_kg/`)
- **Indexing**: Converts text chunks into mathematical vectors using **`BAAI/bge-m3`** (generating dense 1024-dimensional semantic vectors and BM25-like sparse lexical vectors) and stores them in a local embedded **Qdrant database**. 
- To save CPU overhead, it utilizes a JSON manifest file to perform **incremental indexing**, ensuring only new chunk files are processed on successive runs.
- **Querying**: Implements search-retrieval mechanisms:
  - **Multi-Querying**: Expands single queries into five semantic variations to increase search coverage.
  - **Hybrid Search**: Combines dense (concept matching) and sparse (keyword matching) scores using **RRF (Reciprocal Rank Fusion)**.
  - **Knowledge Graph (KG)**: Enhances context by extracting related entity links from a graph database (`knowledge_graph.json`).
  - **Parent-Child Expansion**: Searches small child chunks to maintain semantic precision, but maps matching results back to their parent text chunks to give the LLM full contextual paragraphs.
  - **Inference Answering**: Dispatches queries and context to your locally running **Ollama** server using the `qwen2.5:3b` model to write cohesive, grounded answers.

### Step 5: Web UI Application (`05_webui/`)
- Provides a Flask-based web interface to interact with your documents.
- Features **Lazy Loading**: The Flask web server boots up instantly, deferring the loading of heavy deep learning models and database locks until the first query is sent or the initialization button is clicked.
- Connects directly to the Stage 4 RAG pipeline, retrieves relevant document blocks, visualizes the Knowledge Graph entities, and serves source PDF documents from `used_files/` directly to the web browser.

---

## 3. File-by-File Guide: Core Scripts and Modules

### Directory: `01_preprocessing/`

#### 1. [`run_stage1.py`](file:///C:/Users/hp/Desktop/Rag2/FG/01_preprocessing/run_stage1.py)
* **What it takes**: PDF files placed inside `input_pdfs/`.
* **What it does**: Uses `PyMuPDF` to render PDF pages into images at 450 DPI. It performs image preprocessing (denoising, deskewing, stamp detection) and outputs pages as high-resolution PNGs.
* **What it outputs**: Folder for each PDF containing rendered page images and a `metadata.json` under `stage1_output/`.

#### 2. [`run_stage2.py`](file:///C:/Users/hp/Desktop/Rag2/FG/01_preprocessing/run_stage2.py)
* **What it takes**: PNG page images inside `stage1_output/`.
* **What it does**: Serves as the orchestrator for Stage 2 OCR. It invokes Docling to parse pages, extracts Hindi/English tables and structures, maps page confidence metrics, and cleans up Stage 1 image footprints. It also moves the processed raw PDFs to `used_files/`.
* **What it outputs**: `structured.md`, `structured.json`, and `<doc>_confidence.json` under `stage2_output/`.

#### 3. [`stage2_ocr/docling_ocr.py`](file:///C:/Users/hp/Desktop/Rag2/FG/01_preprocessing/stage2_ocr/docling_ocr.py)
* **What it does**: Core OCR library integration. Runs Docling's converter, processes images, parses tables into plain-text formats, and handles page-level OCR confidence score extraction. It features a custom robust fallback average function that parses OCR text cells to calculate math-average confidence levels when native Docling confidence structures are missing.

#### 4. [`stage2_ocr/pipeline.py`](file:///C:/Users/hp/Desktop/Rag2/FG/01_preprocessing/stage2_ocr/pipeline.py)
* **What it does**: Inner pipeline driver. Oversees batches of page processing, manages directory paths, logs conversion durations, and handles output file writes.

---

### Directory: `02_optimization/`

#### 1. [`optimize.py`](file:///C:/Users/hp/Desktop/Rag2/FG/02_optimization/optimize.py)
* **What it takes**: Raw `structured.md` files from Stage 2.
* **What it does**: Executes a multi-pass clean-up of the Markdown text. Normalizes page-break dividers, fixes overlapping table grid rows, merges hyphens at line endings, corrects out-of-order lists, and strips out single-character extraction artifacts.
* **What it outputs**: A cleaned Markdown file (reduced in size by up to 20-30% by eliminating structural noise).

#### 2. [`spellv2.py`](file:///C:/Users/hp/Desktop/Rag2/FG/02_optimization/spellv2.py)
* **What it takes**: Cleaned Markdown text files.
* **What it does**: Loads a custom Devanagari dictionary and builds a SymSpell corrector. It iterates through words, repairs Hindi OCR typos within designated length parameters, and automatically boosts the frequencies of correctly matched words in the spelling dictionary file.
* **What it outputs**: A spell-corrected Devanagari Markdown document ready for chunking.

---

### Directory: `03_chunking/`

#### 1. [`chunk_stage2_output.py`](file:///C:/Users/hp/Desktop/Rag2/FG/03_chunking/chunk_stage2_output.py)
* **What it takes**: Cleaned and optimized Markdown documents.
* **What it does**: Dedicated OCR pipeline chunker. Uses Docling's `HybridChunker` to semantically divide the Markdown text. Heuristically tracks page numbers using `<!-- Page X -->` comments and prepends a structured header to every `.txt` chunk detailing its source document, pages, token length, and active headings.
* **What it outputs**: Numbered `.txt` text chunks and a master `{doc}_chunks_metadata.json` under `03_chunking/output/`.

#### 2. [`docling_chunker.py`](file:///C:/Users/hp/Desktop/Rag2/FG/03_chunking/docling_chunker.py)
* **What it does**: Generic, configuration-driven chunking utility. Integrates with the central `config_manager` to fetch global paths, batch-processes files matching search wildcards, and utilizes external naming lists (`files.txt`) to restore original PDF names.

---

### Directory: `04_embeddings_and_kg/`

#### 1. [`embeddings_production.py`](file:///C:/Users/hp/Desktop/Rag2/FG/04_embeddings_and_kg/scripts/embeddings_production.py)
* **What it takes**: Generated chunk `.txt` files inside `03_chunking/output/`.
* **What it does**: The production indexing pipeline. Reads a manifest file (`.embeddings_manifest.json`) to skip already-indexed files. Encodes only new chunks using the dense/sparse BGE-M3 model, uploads them to local Qdrant, and updates the manifest. Offers flags for `--status` and database `--recreate`.
* **What it outputs**: Uploads vectors directly to Qdrant collection `db3` and updates `.embeddings_manifest.json`.

#### 2. [`embeddings.py`](file:///C:/Users/hp/Desktop/Rag2/FG/04_embeddings_and_kg/scripts/embeddings.py)
* **What it does**: Standalone indexer and test module. Indexes all files from scratch and provides an interactive CLI search query terminal supporting dense/sparse hybrid search, Reciprocal Rank Fusion (RRF), and cross-encoder reranking.

#### 3. [`index_new_chunks.py`](file:///C:/Users/hp/Desktop/Rag2/FG/04_embeddings_and_kg/scripts/index_new_chunks.py)
* **What it does**: A basic utility script that indexes a target folder's chunks into Qdrant `db3` by mapping next available point IDs sequentially.

#### 4. [`rag_pipeline.py`](file:///C:/Users/hp/Desktop/Rag2/FG/04_embeddings_and_kg/scripts/rag_pipeline.py)
* **What it does**: The primary RAG query orchestrator. It expands query search terms into multiple variations, executes a hybrid dense/sparse search on Qdrant, integrates Knowledge Graph entity associations, and feeds the compiled prompt context to your local Ollama LLM (Qwen) to generate structured, cited answers.

#### 5. [`rag_pipeline_parent_child.py`](file:///C:/Users/hp/Desktop/Rag2/FG/04_embeddings_and_kg/scripts/rag_pipeline_parent_child.py)
* **What it does**: Advanced parent-child retrieval pipeline. Searches child chunk vectors in Qdrant, resolves their parent IDs, loads the larger raw parent paragraphs from disk, reranks them, and streams the context to Ollama to generate highly grounded answers.

---

### Directory: `05_webui/`

#### 1. [`app.py`](file:///C:/Users/hp/Desktop/Rag2/FG/05_webui/app.py)
* **What it takes**: HTTP requests from the browser frontend.
* **What it does**: The web application's Flask backend. It lazy-loads the deep learning libraries only on the first query request (speeding up startup). It exposes REST endpoints for checking database status, executing RAG queries, modifying parameters (KG weight, number of retrieved results), and streaming source PDFs from `used_files/` directly to the web client.
* **What it outputs**: A Flask web server listening on `http://localhost:5000`.

---

## 4. Beginner Quick-Start: Step-by-Step Commands

Follow this simple execution sequence to run the entire pipeline end-to-end:

### 1. Preprocessing & OCR
Copy your PDF files into `01_preprocessing/input_pdfs/`, then run:
```powershell
# 1. Convert PDF to images
python 01_preprocessing/run_stage1.py

# 2. Extract structured OCR Markdown
python 01_preprocessing/run_stage2.py
```

### 2. Markdown Text Optimization
Clean spelling typos and formatting structures:
```powershell
# 1. Strip structural noise
python 02_optimization/optimize.py

# 2. Apply SymSpell Hindi spell correction
python 02_optimization/spellv2.py
```

### 3. Document Chunking
Divide text into token-sized chunks:
```powershell
python 03_chunking/chunk_stage2_output.py
```

### 4. Vector Database Indexing
Convert chunks to vector embeddings and upload to local Qdrant:
```powershell
# 1. Run incremental production indexing
python 04_embeddings_and_kg/scripts/embeddings_production.py
```

### 5. Launch the RAG Web UI
Boot up the interactive web application:
```powershell
# 1. Start Flask web server (Ensure Ollama is running Qwen in the background!)
python 05_webui/app.py
```
Open `http://localhost:5000` in your web browser to start asking questions.
