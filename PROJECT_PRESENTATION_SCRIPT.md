# CHiPS-RTI Project — 15-Minute Presentation Script

**Suggested title:** *From Scanned RTI Documents to Trusted, Explainable Answers*

**Audience:** technical and program stakeholders

**Length:** approximately 15 minutes, including a short live demonstration

**How to use this file:** text in quotation marks is the suggested narration. Text in brackets is a stage direction or demo cue. The exact screen layout may differ slightly between development and deployment environments.

---

## 0:00–1:00 — Opening: the problem and the goal

**[Show the title and one example of a scanned RTI document.]**

“This project addresses a practical problem in public-information workflows. RTI material often arrives as scanned PDFs, in multiple languages, with inconsistent formatting, tables, stamps, and handwritten or low-quality text. A user should not have to search through those files manually to find either a legal answer or the correct Public Information Officer.

The goal of CHiPS-RTI is to convert that difficult document collection into a reliable question-and-answer system. It has two complementary capabilities: first, it can retrieve grounded legal and RTI guidance; second, it can return authoritative officer-directory information such as an office, designation, email, or address. The system also supports a PIO-focused analysis workflow and an evaluation center so that quality can be measured continuously.”

## 1:00–2:00 — What the system delivers

**[Show this flow on a slide or whiteboard.]**

```text
PDFs and web data
       |
       v
Preprocess -> OCR -> Optimize -> Chunk
       |
       v
BGE-M3/Qdrant + PostgreSQL officer registry
       |
       v
Node UI -> Flask API -> semantic route -> grounded answer
       |
       v
Sources, PIO analysis, and evaluation results
```

“The project is organized as a pipeline rather than one large script. The `FG` folder contains the main five-stage flow. `Scraper` maintains external officer and decision data. The web application is split into a Node-based UI and proxy layer and a Flask backend. PostgreSQL is used for canonical officer records, while Qdrant stores searchable document knowledge.

That separation matters. Document processing can be rerun without changing the user interface. Retrieval can evolve without rewriting OCR. And the evaluation service can test a new configuration without mixing benchmark data into the live answer path.”

## 2:00–3:30 — Stage 1: making scanned documents usable

**[Show `FG/01_preprocessing/run_stage1.py` and one before/after page image.]**

“The first stage is preprocessing. The system takes source PDFs and renders pages at a resolution suitable for OCR. It applies operations such as denoising, deskewing, and stamp or artifact handling before recognition. The OCR layer can use the configured document and vision tools, including Docling and the available OCR backends.

The important output is not just plain text. The pipeline preserves page-level and document-level structure and writes intermediate artifacts that can be inspected. That gives us traceability: if an answer looks wrong later, we can go back to the page and compare the recognized text with the original scan.

This stage is especially important for bilingual material. Hindi and English text can appear in the same corpus, and visual cleanup has a direct effect on whether later language detection, chunking, and retrieval succeed.”

## 3:30–4:45 — Stage 2: normalization and correction

**[Show `FG/02_optimization/optimize.py` and `spellv2.py`.]**

“The second stage normalizes the OCR result. OCR frequently produces broken whitespace, inconsistent headings, table artifacts, and small recognition errors. The optimizer cleans Markdown, repairs layout patterns where possible, and applies the configured Hindi spelling correction and dictionaries.

This is not cosmetic formatting. Retrieval depends on stable text. If the same office name or legal term is represented in several noisy forms, both keyword and vector retrieval become less reliable. The optimized Markdown and JSON artifacts create a consistent handoff to chunking, while still preserving enough metadata to locate the original source page.”

## 4:45–6:00 — Stage 3: structure-aware chunks

**[Show a sample chunk with heading, page, source, and parent metadata.]**

“Stage three creates retrieval units. The project includes Docling-based and Markdown-guided chunkers, with semantic and structure-aware behavior. Instead of cutting every document at an arbitrary character count, the chunker uses headings, paragraphs, tables, and page boundaries where available.

Each chunk carries metadata such as the source document, page, section, language, and—where enabled—parent-child relationships. The result is a better balance between context and precision. A small chunk can match a question accurately, while a parent relationship lets the answer-generation step recover surrounding context when the smaller piece alone is not enough.”

## 6:00–7:30 — Stage 4: indexing and retrieval

**[Show Qdrant collections or the Stage 4 scripts.]**

“The fourth stage turns those chunks into searchable knowledge. The primary embedding path uses BGE-M3, with dense and sparse representations. Qdrant supports the vector collections and can be configured for local development or a remote server. The indexing scripts also maintain an incremental manifest, so unchanged content does not need to be embedded repeatedly.

At query time, the retrieval layer can expand a question into multiple searches, combine dense and sparse results using reciprocal-rank fusion, and optionally rerank the candidates. Legal guidance, FAQs, precedents, and the PIO directory can be represented in separate collections. This lets the application choose the right evidence source rather than treating every record as one undifferentiated search index.”

## 7:30–9:30 — Live query path and semantic routing

**[Demo cue: open the web UI and submit these examples one at a time.]**

1. “Who is the PIO for this office?”
2. “What is the RTI response deadline?”
3. “Give me the PIO contact and explain the first appeal timeline.”
4. “यह जानकारी हिंदी में बताइए।”

“The user request enters through the Node UI and proxy, then reaches the Flask API at `/api/query` or the streaming endpoint. The query router is the decision point. It classifies the request into one of four routes: `POSTGRES`, `QDRANT`, `HYBRID`, or `UNCLEAR`.

The first example should use the PostgreSQL route because officer information is treated as canonical directory data. The second should use the legal Qdrant route. The third is mixed, so the system combines the officer record with legal retrieval. A vague or unsupported question is handled conservatively through the unclear path instead of pretending that an unrelated result is authoritative.

The route is not selected by a hard-coded keyword list alone. The current query router uses a structured semantic decision with a JSON schema, then the retrieval layer executes the selected plan. This is one of the places where the LangChain integration helps: prompt construction, structured parsing, and provider interaction are now composed as reusable runnables while the application keeps its existing provider backends.”

## 9:30–10:45 — Grounded answers, languages, and safety

**[Show the answer, source references, and—if available—the source drawer.]**

“The answer layer treats different evidence types differently. Officer answers are deliberately deterministic: PostgreSQL has precedence, and the language model is not allowed to invent or rewrite official names, email addresses, or locations. If the database has no match, a PIO-specific Qdrant fallback can be used; legal documents are not silently used as an officer-directory substitute.

For legal questions, the answer is generated from retrieved context with a grounding prompt and source metadata. The application can answer in English or Hindi and preserve the user’s requested language. The interface exposes the evidence path so a user can inspect where the answer came from instead of receiving an unexplained sentence.

The PIO workflow extends this with three structured steps: extract the RTI application, perform legal analysis, and produce a visible advisory report. Section 4 verification is optional and guarded by allow-listed sources, extraction checks, caching, rate limits, and audit records. Web content is treated as untrusted until it passes validation.”

## 10:45–12:30 — Evaluation Control Center

**[Open `/evaluation`; show dataset upload, experiment configuration, and results.]**

“A key part of the project is the evaluation section. It is designed for the full loop from uploading a benchmark dataset to storing and comparing every result.

An administrator can upload CSV or JSON cases, define an experiment, and choose retrieval, chunking, embedding, reranker, prompt, model, and judge settings. The service runs cases in the background and records results such as Precision at K, Recall at K, MRR, nDCG, route correctness, latency, token usage, and estimated cost. Optional model-based judging adds faithfulness, context relevance, citation correctness, completeness, and hallucination signals. Human review, version records, failure clusters, and regression alerts are also supported.

The storage behavior is now explicit. Evaluation datasets, experiments, results, reviews, versions, and alerts are written through the evaluation service to PostgreSQL. The deployment can use dedicated `RAG_EVAL_POSTGRES_*` settings, or fall back to the configured shared database when that is intentional. The evaluation configuration endpoint and the UI show whether the target is a central server or a local development database. This prevents the common mistake where a benchmark appears successful on one machine but the results are never available to the rest of the team.

In a live demonstration, I would upload a small benchmark, start an experiment, refresh the dashboard, open one case result, and then show the export or comparison view. The important point is that the result is persisted centrally and can be reproduced and compared later.”

## 12:30–13:30 — Operations and deployment model

**[Show `ecosystem.config.js`, the selection server, and the main service boundaries.]**

“There are two common runtime modes. Flask can run directly for development, or the selection server can provide the OTP and session flow, launch the application services, and route users into the Node UI. The Node server proxies API requests to Flask. PM2 configuration supports keeping the Node processes running.

The system is configurable for local Ollama or a remote Sarvam-compatible provider, and for local or remote Qdrant. That gives the team a practical path from laptop experiments to a shared server. At the same time, the deployment audit identifies work still needed before calling this production-hardened: use a production WSGI server, externalize and rotate secrets, configure real domains and CORS, provision durable Qdrant and model storage, and harden authentication, OTP, and process supervision.”

## 13:30–14:30 — What has improved and what to measure next

**[Show a final architecture view or evaluation comparison.]**

“The project’s main improvement is that it now has clear boundaries and measurable behavior. The pipeline separates document quality from retrieval quality. The router separates officer data from legal evidence. LangChain is used where it adds reusable prompt and structured-output composition, without forcing a rewrite of the existing Ollama and Sarvam provider integrations. And the evaluation system makes quality, latency, and cost visible over time.

The next measurements I would prioritize are route accuracy, citation correctness, officer-record exactness, Hindi retrieval quality, end-to-end latency, and regression performance against a versioned benchmark. Those measurements will tell us whether a change improves the user experience or only changes an internal score.”

## 14:30–15:00 — Closing

**[Return to the title slide and show one concise answer with its sources.]**

“To summarize: CHiPS-RTI takes difficult bilingual documents, cleans and structures them, indexes them in the right stores, routes each question to the appropriate evidence source, and returns an answer that can be inspected and evaluated. It is not just a chatbot. It is a document-processing pipeline, a controlled retrieval system, a PIO analysis workflow, and an evaluation loop.

The immediate value is faster access to RTI information with better traceability. The long-term value is a system where improvements can be tested, stored centrally, compared, and promoted with evidence. That is the foundation for making the application more accurate, more maintainable, and safer to deploy.”

---

## Optional backup answers for questions

**Why PostgreSQL and Qdrant together?**

“PostgreSQL is the source of truth for structured officer records. Qdrant is optimized for semantic document retrieval. Keeping those responsibilities separate lets us preserve exact directory values while still searching unstructured legal content effectively.”

**Why not let the language model answer everything?**

“The model is useful for semantic routing, explanation, and grounded legal synthesis. It should not be the authority for exact officer contact data. The route-specific design reduces hallucination risk and makes failures easier to diagnose.”

**Where does LangChain fit?**

“It is used selectively for prompt templates, runnable composition, structured JSON parsing, and streaming prompt handling. The underlying model providers and domain-specific retrieval code remain in the project, so the integration is incremental rather than a wholesale rewrite.”

**What is the biggest production risk?**

“Operational hardening: durable remote storage, secret management, production serving, domain-aware CORS and redirects, and stronger authentication controls. Those are deployment tasks, not reasons to hide the current architecture; they are the next acceptance criteria.”
