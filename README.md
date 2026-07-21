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

## 5. RAG Evaluation and LLMOps Control Center

The evaluation control center answers a question that a normal RAG demo does
not answer: **does a configuration reliably retrieve the right evidence and
produce a grounded answer?**

It runs benchmark questions through the real CHiPS RTI routing, PostgreSQL,
Qdrant, reranking, prompt, and LLM paths. It stores case-level evidence and
metrics in PostgreSQL so experiments can be inspected, compared, reviewed, and
checked for regression.

The feature is integrated into the existing Flask and browser application. It
does not require a separate FastAPI or React service.

### 5.1 What is implemented

- Admin-only evaluation dashboard at `/evaluation`.
- UTF-8 CSV and JSON benchmark upload.
- Ground-truth answers, relevant documents, citations, and expected routes.
- Dense, sparse-candidate, and hybrid retrieval modes.
- Per-experiment embedding, reranker, prompt, answer-model, and judge-model
  selection.
- Optional knowledge-graph, multi-query, reranker, and LLM-judge switches.
- Precision@K, Recall@K, MRR, nDCG, context relevance, faithfulness, citation
  correctness, answer completeness, hallucination risk, and route correctness.
- Mean and P95 latency, token usage, and estimated Sarvam cost.
- Immutable experiment configurations and component version records.
- Baseline regression checks, latency checks, and hallucination alerts.
- Rule-based failure clustering with all applicable failure tags retained.
- Human review forms with four 1-to-5 scores and reviewer notes.
- Side-by-side experiment comparison and case-level CSV export.
- Protected Prometheus metrics for external monitoring and Grafana.

### 5.2 Architecture and runtime flow

```text
Admin browser
    |
    | PIO bearer session
    v
Flask evaluation API
    |
    +--> PostgreSQL evaluation tables
    |      datasets, cases, experiments, results,
    |      reviews, versions, and alerts
    |
    +--> In-process experiment worker
           |
           +--> LLM query router
           |      POSTGRES / QDRANT / HYBRID / UNCLEAR
           |
           +--> PostgreSQL officer registry
           +--> Qdrant legal and PIO collections
           +--> Optional KG and cross-encoder reranker
           +--> Sarvam or Ollama answer model
           +--> Deterministic metrics
           +--> Optional LLM quality judge
           +--> Aggregation, cost, clusters, and alerts
```

One benchmark case uses the same retrieval and answer services as the normal
assistant. A PostgreSQL-only officer answer may be deterministic, while legal
Qdrant and unclear routes can invoke the configured LLM. Router, answer, and
judge token usage is captured separately and then totaled.

### 5.3 Prerequisites

Before opening the control center, verify the following:

1. PostgreSQL is running and the normal officer-registry connection variables
   are valid.
2. Qdrant is available for experiments that need vector retrieval.
3. The selected LLM provider is configured. For Sarvam, set `LLM_MODE=sarvam`,
   `SARVAM_API_KEY`, and `SARVAM_MODEL`. For Ollama, make sure the configured
   local model is running.
4. Install dependencies from the repository root:

```powershell
pip install -r requirements.txt
```

The evaluation schema is created automatically on first use. The PostgreSQL
account therefore needs permission to create tables and indexes in the target
database.

### 5.4 Starting and signing in

Start the existing Flask application:

```powershell
cd FG\05_webui
python app.py
```

Then open `http://localhost:5000` and:

1. Select **PIO Login**.
2. Enter the administrator user ID `admin`.
3. Enter the local administrator password supplied by the project owner.
4. Select **Evaluation center** in the top bar.

The direct URL is `http://localhost:5000/evaluation`.

The current local password requested for this workspace remains valid, but it
is stored as a PBKDF2 hash rather than plaintext. Do not publish the password in
source control or reuse it in production. Citizen accounts and ordinary PIO
accounts receive HTTP 403 from every `/api/evaluation/*` endpoint.

If the **Evaluation center** button is not visible, sign out and sign in again
after restarting Flask. Existing browser sessions created before the admin flag
was added do not contain `isAdmin=true`.

#### First successful experiment

For a first end-to-end run:

1. Create a small benchmark with 5-10 reviewed questions.
2. Open **Benchmarks** and upload it.
3. Open **Experiments** and name the run `current-production-baseline`.
4. Select the uploaded benchmark.
5. Leave **Baseline** as **No baseline**.
6. Choose the Qdrant collection currently used by production.
7. Keep the current embedding and answer models.
8. Use `hybrid`, Top K `5`, Candidate K `20`, dense weight `0.6`, and leave the
   reranker disabled for the initial baseline.
9. Keep the LLM judge enabled if the provider is available; otherwise disable
   it and use deterministic fallback quality scores.
10. Select **Queue experiment** and watch the status move from `QUEUED` to
    `RUNNING` to `COMPLETED`.
11. Select **Inspect** to examine every answer and retrieved document.
12. Open **Human review** and manually score at least a sample of cases.

After the baseline is trusted, duplicate its settings in a second experiment,
select it as the baseline, and change only one variable such as retrieval mode
or reranker status.

### 5.5 Dashboard sections

| Section | Purpose |
|---|---|
| Overview | Counts, latest experiment quality, failure clusters, and open alerts. |
| Benchmarks | Upload, inspect at API level, and delete benchmark datasets. |
| Experiments | Configure, queue, inspect, compare, and export experiment runs. |
| Human review | Score completed case results and save expert notes. |
| Versions | Register chunking, embedding, retrieval, reranker, prompt, and LLM versions. |
| Monitoring | Operational metrics, integration readiness, and alert acknowledgement. |

### 5.6 Building a useful benchmark

A benchmark is a collection of cases. Each case should test one clear user
intent and should contain enough ground truth to evaluate both retrieval and the
answer.

| Field | Required | Meaning |
|---|---:|---|
| `question` | Yes | Exact user question sent through the production router and RAG flow. |
| `expected_answer` | Recommended | Concise ground-truth answer used for completeness scoring. |
| `relevant_documents` | Recommended | Document identifiers that should appear in the top K retrieved results. |
| `expected_citations` | Recommended | Source identifiers that the returned citations should contain. |
| `expected_route` | Optional | `POSTGRES`, `QDRANT`, `HYBRID`, or `UNCLEAR`. |
| `language` | Optional | Usually `en` or `hi`; controls answer language. |
| `category` | Optional | A reporting label such as `pio_lookup` or `section_7`. |
| `tags` | Optional | Free-form benchmark grouping information. |
| `metadata` | Optional | A JSON object containing additional case metadata. |

Accepted aliases are:

- `query` for `question`;
- `ground_truth` or `answer` for `expected_answer`;
- `relevant_docs` or `documents` for `relevant_documents`;
- `citations` for `expected_citations`.

Relevant-document matching checks these returned evidence fields:

- `document_id`
- `source`
- `actual_pdf`
- `retrieval_collection`
- `office_code`
- `email`

Matching is case-insensitive and accepts an exact normalized match or a
substring match of at least four characters. For legal cases, the original PDF
filename is usually the strongest identifier. For PostgreSQL officer cases,
prefer a stable office code or official email address.

#### CSV format

CSV files must be UTF-8. Use `|` or `;` inside a list field. A JSON-encoded list
inside the CSV field is also accepted.

```csv
question,expected_answer,relevant_documents,expected_citations,expected_route,language,category
"Who is the PIO for the example office?","Example Officer is the PIO.","OFFICE-42|pio@example.gov.in","OFFICE-42","POSTGRES","en","pio_lookup"
"What is the normal Section 7 response period?","Information is ordinarily supplied within 30 days.","rti-act.pdf","rti-act.pdf","QDRANT","en","section_7"
"Give the officer email and explain the Section 7 deadline.","The answer should contain both the officer record and the legal deadline.","OFFICE-42|rti-act.pdf","OFFICE-42|rti-act.pdf","HYBRID","en","hybrid"
```

#### JSON format

JSON may be a top-level list or an object containing `cases` or `items`.

A ready-to-upload eight-case starter dataset is included at
[`FG/05_webui/data/rag_evaluation_benchmark_sample.json`](FG/05_webui/data/rag_evaluation_benchmark_sample.json).
It contains reviewed PostgreSQL, Qdrant, and hybrid-routing cases grounded in
the officer registry and legal sources available in this repository.

```json
{
  "cases": [
    {
      "question": "What is the normal Section 7 response period?",
      "expected_answer": "Information is ordinarily supplied within 30 days.",
      "relevant_documents": ["rti-act.pdf"],
      "expected_citations": ["rti-act.pdf"],
      "expected_route": "QDRANT",
      "language": "en",
      "category": "section_7",
      "metadata": {
        "reviewed_by": "legal-team",
        "difficulty": "basic"
      }
    }
  ]
}
```

#### Benchmark-writing recommendations

- Use questions that represent real production traffic.
- Keep one main intent per case unless the case deliberately tests `HYBRID`.
- Use stable document identifiers, not a display title that changes frequently.
- Write expected answers as required facts, not a long stylistic sample.
- Add `expected_route` when routing behavior matters.
- Include both English and Hindi cases when both languages are supported.
- Have a legal or departmental reviewer approve expected answers and citations.
- Start with 20-50 high-quality cases before creating a very large benchmark.

The default limits are 1,000 cases and a 10 MiB uploaded file. Both are
configurable through environment variables.

### 5.7 Uploading a benchmark in the UI

1. Open **Benchmarks**.
2. Enter a unique dataset name and an optional description.
3. Choose the CSV or JSON file.
4. Select **Upload benchmark**.
5. Confirm that the displayed case count matches the file.

Deleting a dataset also deletes its cases, experiments, experiment results,
human reviews, and alerts through PostgreSQL cascade rules. Automatically
registered version records are intentionally retained as an audit trail.

### 5.8 Experiment configuration reference

Open **Experiments**, complete the configuration, and select **Queue
experiment**.

| Setting | Runtime behavior |
|---|---|
| Experiment name | Human-readable immutable run label. |
| Benchmark | Dataset whose cases will be executed. |
| Baseline | Optional completed experiment used for regression detection. |
| Chunking | Provenance label: `current`, `fixed_size`, `recursive`, `semantic`, `page_wise`, `model_assisted`, or `parent_child`. |
| Chunk size | Recorded chunk size, constrained to 64-8,192. |
| Chunk overlap | Recorded overlap, constrained to 0-2,048. |
| Embedding model | BGE-M3-compatible model used to encode experiment queries. It must match the selected collection's indexed vectors. |
| Qdrant collections | Comma-separated pre-indexed collections. Empty means the application's configured defaults. |
| Retrieval | `dense`, `sparse`, or `hybrid`. |
| Hybrid dense weight | Dense contribution from 0 to 1; default is `0.6`. |
| Top K | Number of final results and the K used by Precision@K/Recall@K; range 1-20. |
| Candidate K | Candidates requested per collection; range Top K to 100. |
| Prompt version | Version/audit label for the answer prompt. |
| Prompt instruction | Actual supplementary instruction appended to the grounded RAG prompt. Core safety and grounding rules remain higher priority. |
| Model version | Actual Sarvam or Ollama model identifier used for answer generation. |
| Reranker model | Actual `FlagReranker` model loaded when reranking is enabled. |
| Judge model | Model used for structured answer-quality scoring. |
| Cross-encoder reranker | Enables runtime reranking; the model remains unloaded when disabled. |
| Knowledge graph | Enables the existing legal KG enhancement when available. |
| Multi-query | Selects the multi-query retrieval path. The current focused expansion function emits only the original query. |
| LLM quality judge | Replaces fallback lexical quality scores with structured model scores when successful. |

#### Important chunking and embedding rule

An evaluation run does **not** rechunk documents or rebuild Qdrant. To compare
chunking or embedding strategies correctly:

1. Build a separate Qdrant collection for each strategy.
2. Index the same source documents into each collection.
3. Use the matching embedding model and vector dimensions.
4. Run one experiment per collection while keeping the benchmark and unrelated
   settings unchanged.

For example:

| Experiment | Chunking | Embedding | Collection |
|---|---|---|---|
| `recursive-bge-m3` | recursive | BAAI/bge-m3 | `rti_recursive_bge_m3_v1` |
| `pagewise-bge-m3` | page_wise | BAAI/bge-m3 | `rti_pagewise_bge_m3_v1` |
| `semantic-bge-m3` | semantic | BAAI/bge-m3 | `rti_semantic_bge_m3_v1` |

Changing only the chunking label while querying the same collection does not
constitute a real chunking comparison.

### 5.9 Experiment lifecycle

Experiments move through these states:

```text
QUEUED -> RUNNING -> COMPLETED
                  -> FAILED
```

The configured worker count defaults to one. This is intentional because model
loading, local Qdrant, and GPU memory are expensive resources.

For every case, the worker:

1. asks the LLM router to choose `POSTGRES`, `QDRANT`, `HYBRID`, or `UNCLEAR`;
2. retrieves officer records and/or legal evidence from the selected sources;
3. applies experiment-specific retrieval, KG, embedding, and reranker settings;
4. generates the answer with the selected model and prompt instruction;
5. records route, evidence, citations, warnings, latency, and provider usage;
6. computes deterministic retrieval metrics and fallback quality metrics;
7. optionally runs the structured LLM quality judge;
8. saves the case result and assigns failure tags;
9. aggregates the run after all cases finish;
10. generates quality, latency, and hallucination alerts.

The configuration saved with an experiment does not change after it is queued.
Version records for its major components are also registered automatically.

### 5.10 Understanding the metrics

All quality and retrieval metrics range from 0 to 1 unless otherwise noted.
Higher is better except for `hallucination_score`, latency, token usage, and
cost.

| Metric | Meaning |
|---|---|
| Precision@K | Relevant documents in the first K positions divided by K. Missing positions count as non-relevant. |
| Recall@K | Fraction of expected relevant documents found in the first K positions. |
| MRR | Reciprocal rank of the first relevant result. Rank 1 = 1.0, rank 2 = 0.5. |
| nDCG | Binary-relevance ranking quality with higher-ranked relevant documents receiving more credit. |
| Context relevance | How useful the retrieved context is for the question. |
| Faithfulness | How strongly the answer's claims are supported by retrieved context. |
| Citation correctness | Fraction of expected citations matched by actual returned citation identifiers. |
| Answer completeness | Coverage of the required facts in the expected answer. |
| Hallucination score | Unsupported-claim risk. In fallback mode it is `1 - faithfulness`. |
| Route correctness | 1 when the selected route matches `expected_route`; otherwise 0. It is 1 when no expected route was supplied. |
| Pass rate | Cases without any failure tag divided by all completed cases. |
| Mean latency | Arithmetic mean of end-to-end case latency in milliseconds. |
| P95 latency | 95th-percentile end-to-end case latency. |
| Total tokens | Router, answer-model, and judge tokens reported by providers. |
| Estimated cost | Sarvam token estimate in INR using configured rates. |

#### Deterministic scoring versus LLM judging

Retrieval metrics are always deterministic. Answer-quality metrics have two
modes:

- **Judge enabled and successful:** the configured judge model returns a strict
  JSON object containing relevance, faithfulness, citation correctness,
  completeness, hallucination score, and a short reason.
- **Judge disabled or failed:** token-overlap and identifier-matching fallback
  metrics are used. The result's `judge_details.status` is `disabled` or
  `fallback` so these cases can be identified.

The judge receives at most ten retrieved contexts and at most 4,000 characters
from each context. LLM scores can vary slightly between runs, so use the same
judge model and settings when comparing experiments.

### 5.11 Reading common metric combinations

- **High recall, low precision:** expected evidence is present, but retrieval is
  noisy. Consider reranking, lower Candidate K, or a better collection.
- **Low recall, strong answer completeness:** the model may know or infer the
  answer despite weak retrieval. Treat this as risky rather than successful.
- **High citation correctness, low faithfulness:** the answer cited the expected
  document, but some claims are not supported by its retrieved text.
- **High faithfulness, low completeness:** the answer is safe but omitted
  required facts.
- **Low MRR with good recall:** relevant documents were found but ranked too
  low. A reranker may help.
- **Low route correctness:** fix or retrain routing before tuning the vector
  store.
- **Good quality with high latency:** compare multi-query, KG, reranker, model,
  and Candidate K settings independently.

### 5.12 Failure clusters and tags

A case can have several failure tags, but its cluster is the first applicable
tag in this priority order:

1. `pipeline_error`
2. `routing_failure`
3. `retrieval_miss`
4. `ranking_failure`
5. `hallucination_risk`
6. `citation_failure`
7. `incomplete_answer`
8. `high_latency`
9. `passed`

The current thresholds are:

- retrieval miss: Recall@K is 0 while expected documents were supplied;
- ranking failure: MRR is below 0.5 while expected documents were supplied;
- hallucination risk: faithfulness below 0.65;
- citation failure: citation correctness below 0.65;
- incomplete answer: completeness below 0.65;
- high latency: slower than `RAG_EVAL_LATENCY_WARNING_MS`.

Use `failure_tags` for full diagnosis. The single cluster is intended only for
dashboard grouping.

### 5.13 Baselines, regression tests, and alerts

To run a regression test:

1. Complete a trusted baseline experiment.
2. Queue a new experiment using the same benchmark.
3. Select the trusted experiment in the **Baseline** field.
4. Change one configuration variable.
5. Inspect the new run's alerts and side-by-side metrics.

The service creates a critical `QUALITY_REGRESSION` alert when any comparable
Precision@K, Recall@K, MRR, nDCG, faithfulness, or completeness score drops by
more than `RAG_EVAL_REGRESSION_THRESHOLD`. The default absolute drop is 0.05.

It creates a warning `LATENCY_REGRESSION` alert when mean latency is more than
25% above the baseline. It also creates a warning `HALLUCINATION_RISK` alert for
any completed experiment whose mean faithfulness is below 0.70, even when no
baseline was selected.

Acknowledging an alert hides it from the open-alert count but preserves the
record for audit purposes.

### 5.14 Comparing experiments

Only completed experiments can be compared.

1. Select two or more experiment checkboxes.
2. Select **Compare selected**.
3. Review configuration, retrieval, quality, latency, token, and cost values.
4. Open an individual experiment to inspect each question, expected answer,
   actual answer, evidence, metrics, route, and failure cluster.
5. Select **Export CSV** to download case-level results.

The API compares up to ten distinct experiment IDs per request. For a valid
A/B test, use the same benchmark and change one variable at a time.

### 5.15 Human evaluation

Automated metrics cannot fully judge legal usefulness or writing quality. The
**Human review** section provides four 1-to-5 scores:

- relevance;
- faithfulness;
- citation correctness;
- completeness.

Select a completed experiment, inspect its expected answer, actual answer, and
evidence, enter the scores, add notes, and select **Save human review**.

There is one review per result and reviewer identity. Saving again updates that
review. Human scores are displayed with the result but do not overwrite the
automated metrics.

### 5.16 Version registry

Every experiment automatically registers the versions in its immutable config.
The **Versions** section can also register a component manually.

Supported types are:

- `chunking`
- `embedding`
- `retrieval`
- `reranker`
- `prompt`
- `llm`

The configuration field must be a valid JSON object, for example:

```json
{
  "temperature": 0.0,
  "owner": "rti-team",
  "change": "Added stricter citation instruction"
}
```

The registry is an audit catalog. Registering a version by itself does not
deploy code or alter a running model. Runtime behavior changes only through the
experiment configuration and the corresponding indexed collection/model.

### 5.17 PostgreSQL data model

The following tables are created automatically:

| Table | Stored data |
|---|---|
| `rag_eval_datasets` | Dataset name, description, creator, and timestamp. |
| `rag_eval_cases` | Questions, answers, relevant documents, citations, and metadata. |
| `rag_eval_experiments` | Status, immutable config, baseline, aggregate metrics, timing, and error. |
| `rag_eval_results` | Actual answer, route, evidence, citations, metrics, usage, cost, clusters, and judge details. |
| `rag_eval_human_reviews` | Reviewer scores, notes, and timestamps. |
| `rag_eval_versions` | Component version audit records. |
| `rag_eval_alerts` | Quality, latency, and hallucination alerts. |

Datasets, cases, experiments, results, reviews, and alerts use foreign keys and
cascade deletion. Version records are independent and survive dataset deletion.

### 5.18 Environment variables

Defaults are documented in `FG/05_webui/.env.example`.

| Variable | Default | Purpose |
|---|---:|---|
| `EVALUATION_ADMIN_USERNAME` | `admin` | PIO username automatically recognized as the evaluation admin. |
| `RAG_EVAL_MAX_CASES` | `1000` | Maximum cases accepted in one benchmark. |
| `RAG_EVAL_MAX_UPLOAD_BYTES` | `10485760` | Maximum benchmark upload size. |
| `RAG_EVAL_MAX_WORKERS` | `1` | In-process experiment worker threads. |
| `RAG_EVAL_JUDGE_TIMEOUT_SECONDS` | `90` | Per-case quality-judge timeout. |
| `RAG_EVAL_ROUTER_TIMEOUT_SECONDS` | `60` | Per-case query-router timeout. |
| `RAG_EVAL_LATENCY_WARNING_MS` | `15000` | High-latency failure threshold. |
| `RAG_EVAL_REGRESSION_THRESHOLD` | `0.05` | Absolute quality drop that triggers an alert. |
| `SARVAM_INPUT_COST_PER_1M_INR` | `4` | Estimated uncached input cost per million tokens. |
| `SARVAM_CACHED_INPUT_COST_PER_1M_INR` | `2.5` | Estimated cached input cost per million tokens. |
| `SARVAM_OUTPUT_COST_PER_1M_INR` | `16` | Estimated output cost per million tokens. |
| `MLFLOW_TRACKING_URI` | empty | Marks MLflow as configured in the monitoring panel. |
| `LANGFUSE_PUBLIC_KEY` | empty | Marks Langfuse as configured when present. |
| `LANGFUSE_SECRET_KEY` | empty | Reserved for Langfuse publishing integration. |
| `LANGFUSE_HOST` | empty | Optional Langfuse host. |

Cost is an estimate, not an invoice. Only Sarvam usage is priced by the current
implementation. Ollama/local calls can report tokens but have zero estimated
provider cost. Update the rates whenever provider pricing changes.

### 5.19 API authentication

All evaluation APIs require the bearer token returned by `/auth/login`. Tokens
are stored in process memory and expire according to
`AUTH_SESSION_TTL_SECONDS`, which defaults to eight hours.

PowerShell example:

```powershell
$evalLoginBody = @{
    identifier = "admin"
    password = "<local-admin-password>"
    accountType = "pio"
} | ConvertTo-Json

$evalSession = Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:5000/auth/login" `
    -ContentType "application/json" `
    -Body $evalLoginBody

$evalHeaders = @{
    Authorization = "Bearer $($evalSession.token)"
}

Invoke-RestMethod `
    -Uri "http://localhost:5000/api/evaluation/dashboard" `
    -Headers $evalHeaders
```

Do not print, log, or commit the bearer token.

### 5.20 Evaluation API reference

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/evaluation/config` | Available strategies, collections, active models, and integration readiness. |
| GET | `/api/evaluation/dashboard` | Counts, recent experiments, clusters, and alerts. |
| GET | `/api/evaluation/datasets` | List benchmark datasets. |
| POST | `/api/evaluation/datasets` | Create a dataset from a JSON `cases` list. |
| POST | `/api/evaluation/datasets/upload` | Upload multipart CSV or JSON. |
| GET | `/api/evaluation/datasets/<id>` | Get a dataset and all cases. |
| DELETE | `/api/evaluation/datasets/<id>` | Delete a dataset and dependent experiment data. |
| GET | `/api/evaluation/experiments` | List experiment history. |
| POST | `/api/evaluation/experiments` | Create and queue an experiment. |
| GET | `/api/evaluation/experiments/<id>` | Get configuration, aggregate metrics, and case results. |
| GET | `/api/evaluation/experiments/<id>/export.csv` | Download case-level CSV. |
| POST | `/api/evaluation/compare` | Compare two to ten experiments. |
| POST | `/api/evaluation/results/<id>/review` | Create or update a human review. |
| GET | `/api/evaluation/versions` | List component versions. |
| POST | `/api/evaluation/versions` | Register or update a version record. |
| POST | `/api/evaluation/alerts/<id>/acknowledge` | Acknowledge an alert. |
| GET | `/api/evaluation/metrics` | Protected Prometheus text exposition. |

#### Creating an experiment through the API

```json
{
  "name": "hybrid-reranker-baseline",
  "dataset_id": "<dataset-uuid>",
  "baseline_experiment_id": null,
  "config": {
    "chunking_strategy": "semantic",
    "chunk_size": 512,
    "chunk_overlap": 64,
    "embedding_model": "BAAI/bge-m3",
    "collection_names": ["rti_semantic_bge_m3_v1"],
    "retrieval_mode": "hybrid",
    "hybrid_alpha": 0.6,
    "top_k": 5,
    "candidate_k": 20,
    "reranker_enabled": true,
    "reranker_model": "BAAI/bge-reranker-v2-m3",
    "use_kg": true,
    "use_multi_query": false,
    "prompt_version": "answer-v2",
    "prompt_instruction": "Answer concisely and state the statutory deadline.",
    "model_version": "sarvam-105b",
    "judge_enabled": true,
    "judge_model": "sarvam-105b"
  }
}
```

The create endpoint returns HTTP 202 because execution continues in the
background. Poll the experiment detail endpoint until `status` is `COMPLETED`
or `FAILED`.

### 5.21 Prometheus and Grafana

The protected endpoint is:

```text
GET /api/evaluation/metrics
```

It exposes:

- `rag_eval_datasets_total`
- `rag_eval_experiments_total`
- `rag_eval_experiments_running`
- `rag_eval_alerts_open`
- `rag_eval_experiment_<metric>{experiment_id="..."}` for numeric metrics in
  recent completed experiments.

Example local check:

```powershell
Invoke-WebRequest `
    -Uri "http://localhost:5000/api/evaluation/metrics" `
    -Headers $evalHeaders
```

Prometheus can send an `Authorization: Bearer ...` header, but the current token
is an expiring in-memory user session. For unattended production scraping, add
a dedicated scoped service-token mechanism rather than embedding an admin
password or browser token in Prometheus configuration. Grafana should query
Prometheus, not the Flask endpoint directly.

### 5.22 MLflow, Langfuse, and external evaluators

The monitoring panel currently reports whether MLflow and Langfuse environment
settings are present. It does **not** yet publish MLflow runs or Langfuse traces,
and neither SDK is required by the current application.

The built-in evaluator provides deterministic metrics plus an optional Sarvam
or Ollama structured judge. RAGAS and DeepEval are not invoked. They can be
added later as extra evaluator adapters without changing the benchmark,
experiment, result, or dashboard tables.

### 5.23 Recommended experiment sequence

Run experiments in this order so each result is interpretable:

1. **Current baseline:** current collection and production settings.
2. **Retrieval mode:** dense versus sparse-candidate versus hybrid.
3. **Top K and Candidate K:** tune result count without changing models.
4. **Reranker:** compare disabled versus enabled, then compare reranker models.
5. **Prompt:** keep retrieval fixed and change only prompt version/instruction.
6. **Answer model:** keep contexts and judge fixed while changing the answer
   model.
7. **Chunking:** compare separately indexed collections.
8. **Embedding:** compare compatible separately indexed collections.
9. **Judge audit:** manually review a sample to check whether the judge agrees
   with legal experts.

Use the same benchmark and judge model across a comparison. If two or more
variables change, the dashboard can show which run won but cannot explain why.

### 5.24 Current operational limits

- Chunking selections are provenance plus collection mapping; runs do not
  rechunk or reindex source documents.
- The current sparse mode scores sparse payloads within the dense candidate
  pool. It is not a completely independent sparse-only Qdrant ANN request.
- The current focused multi-query expansion returns only the original query.
- Experiment workers live inside the Flask process. Restarting Flask interrupts
  active runs and may leave a run marked `RUNNING` until it is repaired in the
  database.
- There is no current cancel, retry, or single-experiment delete endpoint.
- Switching large embedding or reranker models can consume substantial RAM,
  VRAM, disk, and model-download time.
- Failure clustering is threshold/rule based; it is not semantic clustering.
- LLM judging adds latency, token cost, and limited nondeterminism.
- MLflow/Langfuse publishing, RAGAS/DeepEval adapters, a Grafana dashboard file,
  and Docker orchestration are not part of the current implementation.

### 5.25 Troubleshooting

#### Evaluation button is missing

- Confirm **PIO Login** was selected, not Citizen Login.
- Confirm the PIO username is `admin` or matches
  `EVALUATION_ADMIN_USERNAME`.
- Confirm the account is active and has `isAdmin: true`.
- Restart Flask and sign in again to obtain a fresh session.

#### HTTP 401 or 403

- 401 means the token is missing, expired, or was created before Flask
  restarted.
- 403 means the authenticated user is not both a PIO and an evaluation admin.

#### Qdrant says the local database is already accessed

Embedded Qdrant allows only one process to own the local storage path. Stop old
`python app.py` processes before restarting, or configure a remote Qdrant
server. Do not point two Flask workers at the same embedded directory.

#### Collection is missing or vector dimensions do not match

The selected collection must exist and must have been indexed with the selected
embedding model and vector schema. Use the collection list shown by the control
center and verify the indexing manifest.

#### Experiment is completed but retrieval metrics are zero

- Check that benchmark identifiers match `source`, `actual_pdf`, `document_id`,
  collection, office code, or email values returned by the result.
- Check the selected Qdrant collection.
- Inspect route correctness before changing retrieval settings.

#### Citation correctness is zero

Expected citations are compared against returned citation identifiers, not
against answer prose. Use stable source identifiers in the benchmark.

#### Cost remains zero

- PostgreSQL-only or local Ollama calls may have zero provider cost.
- The provider must return token-usage fields.
- Only Sarvam calls are priced by the current estimator.

#### PostgreSQL schema creation fails

Verify `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, and
`POSTGRES_PASSWORD`, and confirm that the user can create tables and indexes.

#### Judge falls back

Open the case result and inspect `judge_details`. Common causes are a timeout,
missing API key, unavailable model, malformed provider JSON, or an unsupported
structured-output response.

### 5.26 Verification commands

Run the evaluation and related regression tests from the repository root:

```powershell
python -m pytest `
  FG/05_webui/test_evaluation_service.py `
  FG/04_embeddings_and_kg/scripts/test_parallel_collection_retrieval.py `
  tests/test_frontend_language_localization.py `
  tests/test_language_behavior.py `
  -q -p no:cacheprovider
```

Check Python and browser-script syntax:

```powershell
python -m py_compile `
  FG/05_webui/app.py `
  FG/05_webui/services/evaluation_service.py `
  FG/05_webui/services/llm_provider.py `
  FG/05_webui/services/unified_answer_service.py `
  FG/04_embeddings_and_kg/scripts/rag_pipeline.py

node --check FG/05_webui/nodejs/public/evaluation.js
```

---

## 6. User Query to Final Response: Exact Runtime Flow

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
