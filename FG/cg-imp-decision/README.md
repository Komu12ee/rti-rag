# CGSIC Important Decisions Pipeline

This folder contains an isolated ingestion pipeline for
`Imp_Dicisions_CGSIC.pdf`.

The compilation contains 454 physical pages and 136 indexed decisions. The
decision body occupies physical pages 18-453. The source PDF uses legacy Hindi
fonts, so its selectable text is retained only for diagnostics and every body
page is routed through Project B's existing Hindi/English OCR pipeline.

## Architecture

```text
Imp_Dicisions_CGSIC.pdf
  -> verified 136-decision manifest
  -> individual decision PDFs
  -> Project B Stage 1 image preparation
  -> Project B Stage 2 Docling/EasyOCR
  -> page-wise Unicode checkpoints
  -> per-decision structured.md / structured.json
  -> CGSIC legal JSONL chunks
  -> BGE-M3 embeddings
  -> Qdrant collection cgsic_important_decisions_v1
```

The existing CIC chunker, collection, and retrieval code are not modified.

## Commands

Use the Project B Python environment:

```powershell
$python = "C:\Users\hp\anaconda3\envs\rti\python.exe"
```

Build the verified manifest:

```powershell
& $python FG\cg-imp-decision\cgsic_pipeline.py manifest
```

Split the compilation into 136 independent PDFs:

```powershell
& $python FG\cg-imp-decision\cgsic_pipeline.py split
```

Run resumable OCR. For a bounded first run:

```powershell
& $python FG\cg-imp-decision\cgsic_pipeline.py ocr --start-page 18 --end-page 30
```

Run all decision-body pages:

```powershell
& $python FG\cg-imp-decision\cgsic_pipeline.py ocr
```

Existing page checkpoints are skipped automatically. Reprocess a range with
`--force`.

Assemble per-decision full documents:

```powershell
& $python FG\cg-imp-decision\cgsic_pipeline.py assemble
```

Create CGSIC legal chunks:

```powershell
& $python FG\cg-imp-decision\cgsic_pipeline.py chunk
```

Index into the separate collection:

```powershell
& $python FG\cg-imp-decision\cgsic_pipeline.py index
```

The index command refuses to publish an incomplete corpus. For an isolated
development check only, a partial index can be created with:

```powershell
& $python FG\cg-imp-decision\cgsic_pipeline.py index `
  --qdrant-path FG\cg-imp-decision\artifacts\qdrant_test `
  --allow-partial
```

The default collection is:

```text
cgsic_important_decisions_v1
```

The default Qdrant path is Project B's `qdrant_local_fg`. Override it when
needed:

```powershell
$env:CGSIC_QDRANT_PATH = "C:\path\to\qdrant"
```

The indexer automatically uses a locally cached BGE-M3 snapshot when present,
so indexing can run offline. Set `CGSIC_EMBEDDING_MODEL` to override the model
name or local snapshot path.

Show progress:

```powershell
& $python FG\cg-imp-decision\cgsic_pipeline.py status
```

## Outputs

```text
artifacts/
  decision_manifest.json
  page_text/
    page_018.json
    page_018.txt
  decisions/
    pdf/
      CGSIC_IMPORTANT_001.pdf
    text/
      CGSIC_IMPORTANT_001/
        structured.md
        structured.json
  chunks/
    cgsic_legal_chunks.jsonl
  index_manifest.json
```

Every chunk includes compilation provenance, decision identity, exact physical
and printed page-number lists and ranges, legal chunk type, RTI sections, and
retrieval priority. `source` identifies the original compilation, while
`actual_pdf` and `decision_pdf` identify the corresponding split decision PDF.
