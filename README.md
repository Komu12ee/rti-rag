# The Ultimate Beginner's Guide: Advanced RAG Pipeline (Stages 1-5)

Welcome to the **RAG Pipeline**. This repository contains a production-ready, highly modular Retrieval-Augmented Generation (RAG) system specialized in extracting, cleaning, indexing, and querying complex scanned government and organizational documents (Hindi/English).

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

---

## 5. User Query to Final Response: Exact Runtime Flow

This section explains where the user's query enters the code and how it becomes the final answer shown in the browser.

### A. App launch and service layers

There are two supported ways to reach the RAG UI:

1. **Direct Flask mode**
   - Start `FG/05_webui/app.py`.
   - Open `http://localhost:5000`.
   - Flask serves the frontend from `FG/05_webui/nodejs/public/`.

2. **Selection + proxy mode**
   - Start the selection server from `selection/server.js` or PM2 through `ecosystem.config.js`.
   - The selection server runs on port `3000`.
   - After OTP/session login, `/select` is served by `selection/routes/select.js`.
   - When the user clicks a pipeline card, `/select/launch` calls `launchPipeline()` in `selection/server/utils/pipelines.js`.
   - `launchPipeline()` starts:
     - the Flask backend, for FG usually `FG/05_webui/app.py` on port `5000`;
     - the Node UI/proxy server, `FG/05_webui/nodejs/server.js` on port `3002`.
   - The browser is redirected to the Node UI URL.

In proxy mode, the browser talks to Node first. `FG/05_webui/nodejs/server.js` serves static UI files and proxies `/api/*` requests to the Flask backend. The proxy deliberately re-adds the `/api` prefix before forwarding, so browser `/api/query` becomes Flask `/api/query`.

### B. Where the user query enters the frontend

The user's actual question is typed into the textarea with id `query-input` in the frontend UI.

The active frontend script is:

```text
FG/05_webui/nodejs/public/app.js
```

The important functions are:

- `bootRagUI()`: attaches click and Enter-key handlers to the Send button and query box.
- `sendQuery()`: reads the user's text from `ui.queryInput.value.trim()`.
- `api.query(q, n)`: sends the HTTP request:

```javascript
POST /api/query
{
  "query": "<user question>",
  "num_results": 3
}
```

Before sending, `sendQuery()` also:

- prevents empty queries;
- appends the user's message to the chat window;
- stores the prompt in the session prompt list;
- shows the "thinking" loader;
- disables the query bar while retrieval is running.

### C. Node proxy handling

If the user is using the Node UI on port `3002`, the request goes through:

```text
FG/05_webui/nodejs/server.js
```

Relevant behavior:

- `app.use('/api', apiProxy)` catches `/api/query`.
- `http-proxy-middleware` forwards the request to the Flask URL, usually `http://localhost:5000`.
- `pathRewrite: (path) => '/api' + path` ensures the backend receives `/api/query`, not just `/query`.

This Node layer does not answer the RAG question. It only serves the UI and forwards API/PDF requests.

### D. Flask receives the query

The actual backend endpoint is:

```text
FG/05_webui/app.py
```

The query enters Flask here:

```python
@app.route('/api/query', methods=['POST'])
def query():
```

Inside `query()`:

1. `_load_rag_module()` loads `FG/04_embeddings_and_kg/scripts/rag_pipeline.py` on demand.
2. Flask extracts the JSON body:
   - `query_text = data.get('query', '').strip()`
   - `num_context = data.get('num_results', num_results)`
3. Empty queries are rejected with HTTP `400`.
4. The backend calls `retrieve_context(query_text, num_context=num_context)`.
5. If context exists, the backend calls `generate_answer(query_text, context_results)`.
6. The retrieved chunks are formatted for the UI with source metadata, scores, excerpts, PDF names, legal chunk types, case metadata, and other payload fields.
7. Flask returns JSON with:
   - `success`
   - `query`
   - `answer`
   - `results`
   - `result_count`
   - `execution_time`

### E. RAG retrieval path

The primary retrieval code used by Flask is:

```text
FG/04_embeddings_and_kg/scripts/rag_pipeline.py
```

The main retrieval function is:

```python
retrieve_context(query, num_context=5, use_kg=True)
```

Its process is:

1. `ensure_models_loaded()` loads the BGE-M3 embedding model and reranker lazily.
2. `ensure_qdrant_client()` connects to Qdrant:
   - local embedded Qdrant by default;
   - remote Qdrant if `QDRANT_MODE=remote`.
3. `multi_query_retrieval(query)` expands the user query into several query variations.
4. For each query variation, `perform_single_retrieval(query)`:
   - encodes the query with BGE-M3;
   - creates a dense vector;
   - extracts sparse lexical weights when available;
   - searches Qdrant collection `db3`.
5. Dense results are aggregated across query variations.
6. If sparse weights are available, `sparse_search()` scores keyword overlap.
7. `hybrid_search()` combines dense and sparse scores using Reciprocal Rank Fusion.
8. `apply_legal_priority()` slightly boosts results with legal-priority metadata.
9. If a knowledge graph is loaded, `kg_retriever.enhance_results()` adds entity and relationship signals.
10. Reranking is currently disabled for performance in this pipeline. The code returns the top hybrid results directly.

The returned `context_results` contain Qdrant points. Each point payload normally includes text plus metadata such as source, chunk type, case number, public authority, outcome, hearing date, and retrieval priority.

### F. Answer generation path

The answer is generated in the same file:

```text
FG/04_embeddings_and_kg/scripts/rag_pipeline.py
```

The main function is:

```python
generate_answer(query, context_results)
```

Its process is:

1. It reads the retrieved chunk text from each result.
2. It maps each chunk source to an actual PDF name through `get_actual_filename()`.
3. It builds a source-aware context block:
   - `[Source 1: <pdf name>]`
   - full retrieved chunk text;
   - optional knowledge graph entities.
4. It builds a prompt that instructs the model to:
   - answer only from the provided context;
   - mention source PDFs;
   - cite dates, decisions, approvals, and relevant sections when available.
5. It sends the prompt to local Ollama:

```text
http://localhost:11434/api/generate
```

By default the model is:

```text
qwen2.5:3b
```

This can be changed with the `OLLAMA_MODEL` environment variable.

6. Ollama returns the generated text.
7. `generate_answer()` appends a `Sources used` section listing the PDFs.
8. The final answer string is returned to Flask.

### G. Response returns to the browser

After Flask receives the generated answer:

1. `FG/05_webui/app.py` packages the answer and source results into a JSON response.
2. In proxy mode, `FG/05_webui/nodejs/server.js` passes that JSON back to the browser.
3. In `FG/05_webui/nodejs/public/app.js`, `sendQuery()` receives the JSON.
4. If `data.success` is true:
   - `appendMessage('assistant', data.answer, ...)` renders the final answer in the chat;
   - `state.lastResults = data.results || []` stores the source chunks;
   - `data.execution_time` is shown in the UI;
   - a "View sources" button is attached to the assistant message.
5. When the user clicks "View sources", `openDrawer(results)` displays:
   - rank;
   - source PDF name;
   - similarity score;
   - legal chunk label;
   - passage/excerpt;
   - case and authority metadata when available.
6. When the user clicks "View PDF", `openPdfPanel(fname)` requests:

```text
/01_preprocessing/used_files/<pdf name>
```

That request is served by Flask's `serve_pdf()` endpoint, or proxied through Node in proxy mode.

### H. Short call chain

```text
User types query
  -> FG/05_webui/nodejs/public/app.js: sendQuery()
  -> POST /api/query
  -> optional Node proxy: FG/05_webui/nodejs/server.js
  -> Flask endpoint: FG/05_webui/app.py query()
  -> lazy import: FG/04_embeddings_and_kg/scripts/rag_pipeline.py
  -> retrieve_context()
  -> multi_query_retrieval()
  -> perform_single_retrieval()
  -> Qdrant collection db3
  -> hybrid_search() + optional KG enhancement
  -> generate_answer()
  -> Ollama /api/generate using qwen2.5:3b
  -> Flask JSON response
  -> frontend appendMessage()
  -> answer and sources shown to user
```
