# FG/01_preprocessing

This folder is the document ingestion front door for the RAG system. It turns raw
PDFs into `structured.md` and `structured.json`, which later stages chunk,
embed, index, retrieve, and use to answer user questions.

There are now two supported preprocessing paths:

- **Legacy two-stage path**: `run_stage1.py` rasterizes every PDF page, then
  `run_stage2.py` OCRs every page image.
- **Smart page-level path**: `run_smart_extract.py` first checks whether each
  PDF page contains an image. Image-bearing pages are rasterized and OCRed;
  pages without images keep their selectable text.

The chunker contract is unchanged:

```text
FG/01_preprocessing/stage2_output/<pdf_stem>/structured.md
FG/01_preprocessing/stage2_output/<pdf_stem>/structured.json
```

Any downstream code that reads `stage2_output/**/structured.md` should continue
to work.

## Folder Map

```text
FG/01_preprocessing/
  input_pdfs/                     # Normal place for new PDFs
  used_files/                     # Processed PDFs may be moved here for compatibility
  processed_manifest.json         # Source of truth for skip/reprocess status
  processing_manifest.py          # Manifest load/save/hash/upsert helpers
  page_classifier.py              # Smart direct-text confidence classifier
  run_smart_extract.py            # New smart page-level extraction entry point
  run_stage1.py                   # Legacy Stage 1 plus --smart wrapper
  run_stage2.py                   # Legacy Stage 2 plus --smart wrapper
  stage1_image_prep/              # Rendering, deskew, stamp detection, image prep
  stage1_output/                  # Temporary legacy image output
  stage2_ocr/                     # Docling plus upload Ollama/Sarvam adapters
  stage2_output/                  # Final structured outputs consumed by chunking
```

## Recommended Path: Smart Extraction

Use this for new work unless you intentionally need the old full-OCR behavior.

```powershell
python FG\01_preprocessing\run_smart_extract.py FG\01_preprocessing\input_pdfs --output FG\01_preprocessing\stage2_output
```

Preview without writing:

```powershell
python FG\01_preprocessing\run_smart_extract.py FG\01_preprocessing\input_pdfs --output FG\01_preprocessing\stage2_output --dry-run
```

Reprocess one already-processed PDF:

```powershell
python FG\01_preprocessing\run_smart_extract.py FG\01_preprocessing\input_pdfs --output FG\01_preprocessing\stage2_output --force --limit 1
```

### Smart CLI Options

```text
input                         PDF file or folder containing PDFs
--output, -o                  Stage 2 output directory
--text-confidence-threshold   Direct-text threshold, default 0.60
--force                       Reprocess PDFs already present in the manifest
--dry-run                     Classify pages and log actions, but write nothing
--limit N                     Process only first N eligible PDFs
--ocr-only                    Force every page through OCR
--direct-text-only            Never invoke OCR, even for image-bearing pages
--ocr-model                    Override OCR_MODEL with ollama or sarvam
--verbose                     Enable debug logging
```

`--ocr-only` and `--direct-text-only` are mutually exclusive.

## Smart Extraction Flow

```text
PDF
  -> open with pdfplumber
  -> for each page, in original page order:
       extract direct text
       if pdfplumber fails or returns empty text:
         try PyMuPDF text fallback
       count embedded/raster images
       if the page has no image:
         use direct text
         do not rasterize this page
         do not call OCR for this page
       else:
         render only this page with ImagePrepPipeline.process_single_page()
         OCR only this prepared image with the configured provider
         use OCR text as final page text
  -> merge pages in original order
  -> write structured.md
  -> write structured.json
  -> write extraction_report.json
  -> write page_debug/page_NNN.txt files
  -> update processed_manifest.json
```

The important rule is page-level routing. One PDF may contain both direct-text
pages and OCR pages.

### Upload OCR Provider

The `+` upload flow reads `FG/05_webui/.env`. The default is local Ollama:

```dotenv
OCR_MODEL=ollama
OLLAMA_OCR_MODEL=qwen3-vl:4b-instruct
```

Install the configured vision model once on the machine running Flask:

```powershell
ollama pull qwen3-vl:4b-instruct
```

To use Sarvam Document Intelligence instead:

```dotenv
OCR_MODEL=sarvam
SARVAM_API_KEY=replace_with_your_key
```

Install the Document Intelligence SDK into the same Python environment that
runs `FG/05_webui/app.py`:

```powershell
python -m pip install "sarvamai>=0.1.28,<0.2.0"
```

`LLM_MODE=sarvam` uses Sarvam's chat-completions HTTP API, while
`OCR_MODEL=sarvam` uses the separate Document Intelligence SDK. Therefore a
working Sarvam LLM does not by itself prove that the OCR dependency is
installed. Restart Flask after changing `.env`; package installation alone is
picked up by the next upload subprocess.

`OCR_MODEL` accepts only `ollama` or `sarvam`. It is an exclusive choice in the
smart extraction and `+` upload path: that path does not call the other provider
as a fallback. Pages that do not need OCR call neither provider.
`OLLAMA_OCR_MODEL` is deliberately separate from `OLLAMA_MODEL`, which remains
the model used for answer generation.

## Smart Output Structure

For `example.pdf`, smart extraction writes:

```text
stage2_output/
  example/
    structured.md
    structured.json
    extraction_report.json
    page_debug/
      page_001.txt
      page_002.txt
```

If all pages pass direct-text confidence, there is no `stage1_output` folder,
no per-page image folder, and no `metadata.json` for that document. That is
expected: the page never needed rasterization.

### `structured.md`

Every page gets a page marker and an extraction metadata comment. The legal
chunker can use these comments later for trust weighting.

```markdown
<!-- Page 1 -->
<!-- extraction_method: direct_text | confidence: 0.87 -->
Final extracted text for page 1

<!-- Page 2 -->
<!-- extraction_method: ocr | confidence: 0.42 -->
Final extracted text for page 2
```

### `structured.json`

```json
{
  "source_pdf": "example.pdf",
  "total_pages": 12,
  "total_text_chars": 18420,
  "overall_confidence": 0.74,
  "pages": [
    {
      "page_num": 1,
      "page_type": "digital_text",
      "direct_text_confidence": 0.87,
      "needs_ocr": false,
      "extraction_method": "direct_text",
      "direct_text": "...",
      "ocr_text": "",
      "final_text": "...",
      "legal_markers_found": ["File No", "Appellant"],
      "char_count": 1540,
      "word_count": 248,
      "reason": "direct_text_confidence=0.87 >= threshold=0.6"
    }
  ],
  "critical_fields": {
    "case_numbers": [],
    "dates": [],
    "sections": [],
    "emails": []
  },
  "quality_flags": []
}
```

## Direct-Text Confidence Logic

The classifier lives in:

```text
FG/01_preprocessing/page_classifier.py
```

It scores extracted page text using:

- character count;
- word count;
- CIC/RTI legal markers such as `File No`, `RTI application`, `Facts`,
  `Order`, `Appellant`, and `Respondent`;
- alphabetic ratio, including Devanagari characters because Python
  `str.isalpha()` treats Devanagari letters as alphabetic;
- noise ratio, including non-printable characters, repeated symbol runs, and
  isolated single-character extraction artifacts.

At the default threshold `0.60`:

- `confidence >= 0.60`: use direct text and skip OCR for that page;
- `confidence < 0.60`: route that page through image prep and OCR.

## Legacy Two-Stage Path

The old pipeline is still available for rollback and comparison.

### Stage 1

```powershell
python FG\01_preprocessing\run_stage1.py
```

What it does:

```text
PDF
  -> PyMuPDF renders every page at configured DPI
  -> deskew
  -> denoise setting currently preserves tiny punctuation
  -> stamp/annotation detection
  -> optional stamp masking
  -> save page_0000.png, page_0001.png, ...
  -> write metadata.json
```

Output:

```text
stage1_output/<pdf_stem>/
  page_0000.png
  page_0001.png
  metadata.json
```

### Stage 2

```powershell
python FG\01_preprocessing\run_stage2.py
```

What it does:

```text
stage1_output/<pdf_stem>/metadata.json
  -> load page images
  -> run Docling OCR/layout extraction
  -> postprocess OCR text
  -> extract dates, amounts, reference numbers
  -> optionally attempt Sarvam fallback if configured and installed
  -> write structured.md and structured.json
  -> update confidence_log.json
```

Output:

```text
stage2_output/<pdf_stem>/
  structured.md
  structured.json
  <pdf_name>_confidence.json

stage2_output/confidence_log.json
```

After successful legacy Stage 2, the script removes the temporary Stage 1 folder
and may move the original PDF to `used_files/`.

## `--smart` Compatibility Wrappers

Both legacy scripts can call the smart extractor:

```powershell
python FG\01_preprocessing\run_stage1.py --smart FG\01_preprocessing\input_pdfs --dry-run
python FG\01_preprocessing\run_stage2.py --smart FG\01_preprocessing\input_pdfs --dry-run
```

Without `--smart`, the scripts preserve legacy behavior and print a deprecation
warning.

## Manifest and Skip Logic

Manifest file:

```text
FG/01_preprocessing/processed_manifest.json
```

The manifest is the source of truth for duplicate prevention. Moving PDFs to
`used_files/` is compatibility behavior, not the primary skip mechanism.

Base schema:

```json
{
  "pdf_name": "CIC_AAOIN_A_2017_102598.pdf",
  "pdf_stem": "CIC_AAOIN_A_2017_102598",
  "source_path": "...",
  "file_size": 12345,
  "sha256": "...",
  "stage1_status": "success",
  "stage2_status": "success",
  "stage1_output_dir": "...",
  "stage2_structured_md": "...",
  "stage2_structured_json": "...",
  "processed_at": "...",
  "updated_at": "...",
  "error": null
}
```

Smart extraction extends entries without breaking the base schema:

```json
{
  "stage1_status": "completed_smart",
  "stage2_status": "completed_smart",
  "overall_confidence": 1.0,
  "extraction_method_summary": {
    "direct_text": 2,
    "ocr": 0,
    "hybrid": 0,
    "failed": 0
  }
}
```

### Default Skip Behavior

Default runs process only new PDFs.

Smart extraction skips a PDF when:

- the manifest entry has `stage2_status` of `success` or `completed_smart`; and
- `stage2_structured_md` exists; and
- `stage2_structured_json` exists; and
- `--force` was not passed.

Legacy Stage 1 skips when:

- Stage 2 already succeeded and structured output exists; or
- Stage 1 already succeeded and `metadata.json` exists.

Legacy Stage 2 skips when:

- Stage 2 already succeeded and both structured files exist; or
- old structured files already exist on disk.

### Force Behavior

Use `--force` when you intentionally want to rebuild output.

```powershell
python FG\01_preprocessing\run_smart_extract.py FG\01_preprocessing\input_pdfs --output FG\01_preprocessing\stage2_output --force
```

Force behavior:

- reprocesses files even if the manifest says they are done;
- deletes old output for that PDF before writing new smart output;
- updates the existing manifest entry rather than appending a duplicate.

### Dry Run Behavior

Use `--dry-run` to preview decisions without writing:

```powershell
python FG\01_preprocessing\run_smart_extract.py FG\01_preprocessing\input_pdfs --output FG\01_preprocessing\stage2_output --dry-run
```

Dry run:

- computes page classification;
- logs `direct_text`, `ocr`, `hybrid`, and `failed` counts;
- does not write output folders;
- does not update the manifest;
- does not load OCR dependencies unless a real OCR run is needed.

## Safe Workflows

### Test One New PDF With Smart Extraction

```powershell
python FG\01_preprocessing\run_smart_extract.py FG\01_preprocessing\input_pdfs --output FG\01_preprocessing\stage2_output --dry-run --limit 1
python FG\01_preprocessing\run_smart_extract.py FG\01_preprocessing\input_pdfs --output FG\01_preprocessing\stage2_output --limit 1
```

Then confirm:

```text
FG/01_preprocessing/stage2_output/<pdf_stem>/structured.md
FG/01_preprocessing/stage2_output/<pdf_stem>/structured.json
FG/01_preprocessing/stage2_output/<pdf_stem>/extraction_report.json
```

### Reprocess All PDFs Safely

Preview first:

```powershell
python FG\01_preprocessing\run_smart_extract.py FG\01_preprocessing\input_pdfs --output FG\01_preprocessing\stage2_output --force --dry-run
```

Then run:

```powershell
python FG\01_preprocessing\run_smart_extract.py FG\01_preprocessing\input_pdfs --output FG\01_preprocessing\stage2_output --force
```

### Legacy Two-Stage Test

```powershell
python FG\01_preprocessing\run_stage1.py --dry-run --limit 1
python FG\01_preprocessing\run_stage1.py --limit 1
python FG\01_preprocessing\run_stage2.py --dry-run --limit 1
python FG\01_preprocessing\run_stage2.py --limit 1
```

## Downstream Pipeline After Preprocessing

Preprocessing is offline ingestion. User queries do not call Stage 1 or Stage 2
directly. The query system depends on the outputs produced here.

The normal offline flow is:

```text
01_preprocessing
  -> stage2_output/<pdf_stem>/structured.md
02_optimization
  -> cleaned/optimized text, depending on selected workflow
03_chunking
  -> legal chunks or semantic chunks
04_embeddings_and_kg
  -> embeddings, Qdrant collection, optional knowledge graph
05_webui
  -> user-facing query interface
```

The legal chunker reads:

```text
FG/01_preprocessing/stage2_output/<pdf_stem>/structured.md
```

It writes retrieval-ready chunks such as:

```text
FG/03_chunking/legal_output/<pdf_stem>/legal_chunks.jsonl
```

The embedding/indexing scripts then store chunk text and metadata into Qdrant,
usually collection `db3`.

## Where The User Query Comes From

The user query begins in the browser UI, not in preprocessing.

Primary frontend:

```text
FG/05_webui/nodejs/public/index.html
FG/05_webui/nodejs/public/app.js
```

The query input DOM element is:

```text
query-input
```

In `app.js`, the important functions are:

- `bootRagUI()`: wires UI events.
- `sendQuery()`: reads `ui.queryInput.value.trim()`.
- `api.query(q, n)`: sends the HTTP request.

The browser sends:

```http
POST /api/query
Content-Type: application/json

{
  "query": "<user question>",
  "num_results": 3
}
```

Before the request is sent, the UI:

- appends the user's message to the chat;
- clears and resizes the text box;
- adds a thinking message;
- disables the query bar with status `Retrieving...`.

## Optional Node Proxy Layer

If running the Node UI server:

```text
FG/05_webui/nodejs/server.js
```

The browser talks to Node first, usually on port `3002`. Node serves static
files and proxies API requests to Flask:

```text
Browser /api/query
  -> Node app.use('/api', apiProxy)
  -> http://localhost:5000/api/query
```

The proxy uses:

```text
pathRewrite: (path) => '/api' + path
```

That is needed because the proxy middleware strips the `/api` mount path before
forwarding.

Node does not run retrieval and does not generate answers. It only serves the
frontend and forwards API/PDF requests.

## Flask Receives The Query

Backend:

```text
FG/05_webui/app.py
```

The query enters Flask here:

```python
@app.route('/api/query', methods=['POST'])
def query():
```

Inside `query()`:

1. `_load_rag_module()` imports `FG/04_embeddings_and_kg/scripts/rag_pipeline.py`
   on demand. This lazy load keeps Flask startup fast.
2. Flask reads JSON from the request.
3. It extracts:

   ```python
   query_text = data.get('query', '').strip()
   num_context = data.get('num_results', num_results)
   ```

4. If `query_text` is empty, Flask returns HTTP `400`.
5. It calls:

   ```python
   context_results = retrieve_context(query_text, num_context=num_context)
   ```

6. If no context is found, Flask returns a successful JSON response with an
   error message and empty results.
7. It calls:

   ```python
   answer = generate_answer(query_text, context_results)
   ```

8. It formats source result metadata for the frontend.
9. It returns JSON:

   ```json
   {
     "success": true,
     "query": "<user question>",
     "answer": "<generated answer>",
     "results": [],
     "result_count": 3,
     "execution_time": "4.21s"
   }
   ```

## Retrieval: `rag_pipeline.py`

Primary RAG code:

```text
FG/04_embeddings_and_kg/scripts/rag_pipeline.py
```

Important config:

```text
COLLECTION_NAME = db3 by default
Qdrant local path = FG/04_embeddings_and_kg/db/qdrant_local by default
OLLAMA_HOST = localhost
OLLAMA_PORT = 11434
OLLAMA_MODEL = qwen2.5:3b
```

Retrieval entry point:

```python
retrieve_context(query, num_context=5, use_kg=True)
```

Retrieval flow:

```text
retrieve_context()
  -> multi_query_retrieval()
     -> expand_query()
     -> perform_single_retrieval() for each query variation
        -> ensure_models_loaded()
           -> load BGE-M3 embedding model
           -> load BGE reranker object, although reranking is currently disabled
           -> load knowledge graph if available
        -> ensure_qdrant_client()
           -> open local or remote Qdrant
        -> encode query with BGE-M3
           -> dense vector
           -> sparse lexical weights if available
        -> qdrant.query_points(collection_name='db3', query=dense_vector)
  -> aggregate dense scores across query variations
  -> sparse_search() if sparse weights exist
  -> hybrid_search() with Reciprocal Rank Fusion
  -> apply_legal_priority() using retrieval_priority payload
  -> optional KG enhancement with kg_retriever
  -> return top context result dicts
```

Each returned result contains a Qdrant point. The point payload is expected to
include fields like:

```text
text
source
file
chunk_type
case_number
public_authority
outcome
hearing_date
retrieval_priority
```

Those fields come from the chunking/indexing stages, not from the live user
query.

## Answer Generation

Answer generation is in the same file:

```python
generate_answer(query, context_results)
```

Flow:

```text
generate_answer()
  -> collect retrieved chunk text from result.point.payload['text']
  -> map chunk source to actual PDF name with get_actual_filename()
  -> include KG entity hints if available
  -> build a prompt containing:
       system instructions
       retrieved context
       user question
  -> POST to Ollama:
       http://localhost:11434/api/generate
       model: qwen2.5:3b
       stream: false
       temperature: 0.3
  -> read response JSON field "response"
  -> append "Sources used"
  -> return final answer string to Flask
```

The LLM is instructed to answer only from the provided context, cite source
PDFs, mention dates/decisions where available, and say clearly when the context
does not contain the information.

## Flask Formats The Response

After `generate_answer()` returns, Flask builds `formatted_results`.

For each retrieved result, Flask includes:

```text
rank
source
actual_pdf
score
text
excerpt
parent_id
chunk_type
case_number
public_authority
outcome
hearing_date
retrieval_priority
precedent_summary
commission_observations
pio_learning_signal
```

The excerpt is produced with `extract_highlighted_excerpt()` from
`rag_pipeline.py` when available.

## Browser Displays The Answer

Back in:

```text
FG/05_webui/nodejs/public/app.js
```

`sendQuery()` receives the Flask JSON response.

If `data.success` is true:

```text
state.lastResults = data.results
appendMessage('assistant', data.answer, { timing, results })
ui.queryTiming.textContent = data.execution_time
```

The assistant answer appears in the chat. If source results exist, the frontend
adds a `View sources` button. Clicking it opens the source drawer.

## Source PDF Viewing

When the user opens a source PDF:

```text
app.js openPdfPanel(fname)
  -> GET /01_preprocessing/used_files/<filename>
```

If Node proxy is used:

```text
Browser /01_preprocessing/used_files/file.pdf
  -> Node pdfProxy
  -> Flask /01_preprocessing/used_files/file.pdf
```

Flask endpoint:

```python
@app.route('/01_preprocessing/used_files/<filename>', methods=['GET'])
def serve_pdf(filename):
```

Flask serves PDFs from:

```text
FG/01_preprocessing/used_files/
```

This is why the legacy Stage 2 movement into `used_files/` still matters for
the UI source-document viewer. Smart extraction uses the manifest as the skip
source of truth, but source-PDF viewing still expects PDFs to be available under
`used_files/` unless the UI/source-serving path is adjusted.

## End-To-End Query Diagram

```text
User types question in browser
  -> app.js sendQuery()
  -> POST /api/query
  -> optional Node proxy server.js
  -> Flask app.py query()
  -> _load_rag_module()
  -> rag_pipeline.py retrieve_context()
     -> expand_query()
     -> BGE-M3 query embedding
     -> Qdrant dense search
     -> optional sparse search
     -> hybrid RRF ranking
     -> legal priority boost
     -> optional knowledge graph enhancement
  -> rag_pipeline.py generate_answer()
     -> build prompt from retrieved chunks
     -> POST Ollama /api/generate
     -> append Sources used
  -> Flask returns JSON
  -> app.js appendMessage('assistant', answer)
  -> user sees final response and source drawer
```

## Important Separation Of Responsibilities

Preprocessing does not answer the user at query time.

Preprocessing is offline:

```text
PDF -> structured.md -> chunks -> embeddings -> Qdrant
```

Query time is online:

```text
question -> retrieve chunks from Qdrant -> generate answer with Ollama
```

So if a user asks a question and gets a poor answer, check:

1. Was the PDF preprocessed into good `structured.md`?
2. Did chunking create useful chunks?
3. Were those chunks indexed into Qdrant collection `db3`?
4. Does `retrieve_context()` return the right chunks?
5. Is Ollama running with `qwen2.5:3b`?

## Troubleshooting

### A PDF Is Skipped But I Want To Rebuild It

Use `--force`:

```powershell
python FG\01_preprocessing\run_smart_extract.py FG\01_preprocessing\input_pdfs --output FG\01_preprocessing\stage2_output --force --limit 1
```

### I Want To See What Will Happen First

Use `--dry-run`:

```powershell
python FG\01_preprocessing\run_smart_extract.py FG\01_preprocessing\input_pdfs --output FG\01_preprocessing\stage2_output --dry-run
```

### I Only Want A Small Test Batch

Use `--limit`:

```powershell
python FG\01_preprocessing\run_smart_extract.py FG\01_preprocessing\input_pdfs --output FG\01_preprocessing\stage2_output --limit 2
```

### The Browser Says Backend Is Unreachable

Check Flask:

```powershell
python FG\05_webui\app.py
```

If using Node UI, check Node too:

```powershell
cd FG\05_webui\nodejs
npm run dev
```

### Query Runs But No Context Is Found

Check Qdrant/indexing:

- confirm embeddings were created from the latest chunks;
- confirm collection `db3` exists;
- confirm `FG/04_embeddings_and_kg/db/qdrant_local` is not locked by another
  process;
- run the retrieval script directly for a known query.

### Answer Generation Fails

Check Ollama:

```powershell
ollama list
ollama run qwen2.5:3b
```

`rag_pipeline.py` calls:

```text
http://localhost:11434/api/generate
```
