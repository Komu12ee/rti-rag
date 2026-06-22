# CGSIC Decision Chunker

`cgsic_decision_chunker.py` converts Project B Stage 2 `structured.json`
documents into reviewable legal chunks. It performs no OCR, embedding, or
Qdrant writes.

## Input

The input directory contains one folder per split decision:

```text
cg-imp-dics-ocr-op/
  CGSIC_IMPORTANT_001/
    structured.json
  CGSIC_IMPORTANT_002/
    structured.json
```

The 136-decision manifest maps decision-relative OCR pages to the printed and
physical pages in `Imp_Dicisions_CGSIC.pdf`.

## Run

From the repository root:

```powershell
python FG\03_chunking\cgsic_decision_chunker.py `
  FG\01_preprocessing\cg-imp-dics-ocr-op `
  --output FG\03_chunking\cgsic_output
```

If the earlier duplicated OCR output has not yet been moved:

```powershell
python FG\03_chunking\cgsic_decision_chunker.py `
  FG\01_preprocessing\FG\01_preprocessing\cg-imp-dics-ocr-op `
  --output FG\03_chunking\cgsic_output
```

The command can be rerun while OCR is progressing. Aggregate outputs are
rewritten from the currently available `structured.json` files.

## Outputs

```text
cgsic_output/
  cgsic_legal_chunks.jsonl
  chunk_quality_report.json
  CGSIC_IMPORTANT_001/
    legal_chunks.jsonl
    chunk_quality_report.json
```

The split validator records appeal-number, order-date, signature, and final
direction counts. Suspect documents remain visible in output with:

```json
{
  "split_quality": "suspect",
  "split_review_required": true
}
```

Review the aggregate `chunk_quality_report.json` before embedding or Qdrant
indexing.
