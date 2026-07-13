# Markdown-Guided Chunking Pipeline

This package learns a reusable Markdown chunking strategy from one or more
sample documents with a local Ollama model. It then generates a standalone
Python script that can chunk a Markdown file or an entire Markdown folder
without calling an LLM at runtime.

The canonical entry point is `cli.py`.

## What This Pipeline Does

- Accepts UTF-8 `.md` files only.
- Parses Markdown into stable, ordered blocks.
- Uses Ollama during analysis to profile document structure and identify
  structural units.
- Reports coverage, ordering, numbering, and size problems without silently
  changing the model's decision.
- Supports an explicit, human-triggered repair pass for selected units or
  block ranges.
- Generates `FG/03_chunking/<strategy>_chunking.py`.
- Lets the generated script process new Markdown files or folders without
  Ollama.
- Emits UTF-8 text chunks, JSONL records, or Qdrant-shaped JSON payloads.

It does not read PDFs, perform OCR, create embeddings, connect to Qdrant, or
upsert vectors. Those are separate pipeline stages.

## Current Two-Phase Design

```text
Analysis and strategy generation (Ollama required)

Markdown sample(s)
  -> Markdown block loader
  -> document profile LLM call
  -> candidate boundaries and analysis windows
  -> boundary-analysis LLM calls
  -> report-only validation
  -> optional manual repair
  -> learned deterministic strategy
  -> FG/03_chunking/<strategy>_chunking.py

Runtime chunking (Ollama not required)

Markdown file/folder
  -> generated <strategy>_chunking.py
  -> deterministic Markdown parsing and learned boundary hints
  -> .txt chunks, JSONL, or Qdrant-shaped JSON
```

The generated script is reusable. It re-reads the runtime Markdown input and
applies learned heading levels, boundary patterns, structural cues, and size
limits. It does not contain a fixed copy of the sample document's final
chunks.

## Prerequisites

- Python 3.10 or newer
- Ollama available during profile, analysis, and repair commands
- Enough memory to run `qwen3:14b`, or a different structured-output-capable
  model configured in `config/model.yaml`

### Windows PowerShell

From the repository root:

```powershell
cd FG\03_chunking\md_guided_chunking
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
ollama pull qwen3:14b
ollama serve
```

Run `ollama serve` in another terminal if Ollama is not already running.
The examples use `python -X utf8` because Hindi output can fail in a default
Windows CP1252 console.

### Linux or macOS

```bash
cd FG/03_chunking/md_guided_chunking
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
ollama pull qwen3:14b
ollama serve
```

## Model Configuration

The current defaults are in `config/model.yaml`:

```yaml
model:
  name: "qwen3:14b"
  temperature: 0
  num_ctx: 16384
  thinking_mode: false
```

Only the following settings are currently consumed by
`llm/ollama_client.py`:

| Setting | Used now | Meaning |
|---|:---:|---|
| `model.name` | yes | Ollama model used for structured analysis |
| `model.temperature` | yes | Generation temperature |
| `model.num_ctx` | yes | Ollama context-window option |
| `model.thinking_mode` | yes | Default `think` value for profile/analysis calls |
| `model.host` | no | Present in YAML but not passed to the Ollama client |
| `windowing.*` | no | CLI defaults are currently defined in `cli.py` |
| `paths.*` | no | CLI output locations are currently defined in `cli.py` |

Manual repair calls force thinking mode on. There is currently no CLI
`--thinking` option. The standard Ollama Python client configuration controls
which Ollama server is contacted; editing `model.host` alone has no effect.

## Recommended Quick Start

Run commands from `FG/03_chunking/md_guided_chunking`.

### Learn From One Markdown File

```powershell
python -X utf8 cli.py run "C:\path\to\manual.md"
```

This runs:

```text
load -> profile -> analyze -> validate -> generate -> review
```

It never invokes `repair` automatically.

### Learn One Strategy From a Folder

```powershell
python -X utf8 cli.py run-all "C:\path\to\markdown_corpus"
```

Folder behavior:

- Markdown discovery is recursive.
- If the folder contains 10 or fewer `.md` files, all files are analysed.
- If it contains more than 10 files, the command randomly samples between 5
  and 10 files.
- One combined reusable strategy script is generated from the analysed
  sample.
- The generated script can then chunk the full folder.

`run-all` also accepts a single `.md` file. Folder sampling currently has no
seed option, so repeated runs over a large folder can learn from different
samples.

Window settings can be overridden for `run`, `run-all`, and `analyze`:

```powershell
python -X utf8 cli.py run-all "C:\path\to\markdown_corpus" `
  --window-size 30 --window-overlap 3
```

## Stage-by-Stage Commands

Use these commands when you want to inspect or control each phase separately.

| Command | Ollama call | Primary result |
|---|:---:|---|
| `load` | no | Parsed block JSON |
| `profile` | one | Document profile JSON |
| `analyze` | one per window | Boundary decision and review report |
| `review` | no | Prints the existing review report |
| `repair` | one targeted call | Repaired decision and rewritten review report |
| `validate` | no | Prints coverage/order/size reports |
| `generate` | no | Writes a reusable strategy script |
| `run` | multiple | Complete single-file flow, excluding repair |
| `run-all` | multiple | File/folder learning flow, excluding repair |

### 1. Parse Markdown Blocks

```powershell
python -X utf8 cli.py load "C:\path\to\manual.md"
```

Writes `analysis/<doc_id>_blocks.json`.

### 2. Build the Document Profile

```powershell
python -X utf8 cli.py profile "C:\path\to\manual.md"
```

Writes `analysis/<doc_id>_profile.json`.

### 3. Analyse Structural Boundaries

```powershell
python -X utf8 cli.py analyze "C:\path\to\manual.md" `
  --window-size 30 --window-overlap 3
```

Writes:

- `analysis/<doc_id>_decision.json`
- `analysis/<doc_id>_review.md`

Every analysis window is sent to the model once. Low confidence and
`needs_review=true` are reported for human review; they do not trigger an
automatic retry.

### 4. Review the Decision

```powershell
python -X utf8 cli.py review "C:\path\to\manual.md"
```

The report is sorted from lowest to highest confidence.

### 5. Repair a Selected Region Manually

By structural identifier:

The value must exactly match an identifier shown in the review report.

```powershell
python -X utf8 cli.py repair "C:\path\to\manual.md" `
  --unit-id "7" --context-blocks 6 `
  --reason "Boundary includes the next section"
```

By raw block range:

```powershell
python -X utf8 cli.py repair "C:\path\to\manual.md" `
  --block-range b0120:b0165 --context-blocks 6
```

Repair behavior:

- The previous decision is copied to
  `analysis/<doc_id>_decision.backup-<UTC timestamp>.json`.
- Units whose start or end block lies inside the selected range are replaced
  with the repair result.
- The current decision JSON is updated.
- The review Markdown is rewritten from the updated decision; it is not
  appended.
- Surrounding blocks are sent to the model as context. The response schema
  does not enforce that every returned unit stays inside the selected range,
  so inspect the printed repair result and updated review carefully.

### 6. Validate

```powershell
python -X utf8 cli.py validate "C:\path\to\manual.md"
```

Validation reports:

- missing or multiply covered block IDs;
- reversed or overlapping unit ranges;
- simple numeric identifier gaps;
- units estimated below 50 or above 900 tokens.

Token counts use a rough `characters / 4` estimate. Validation only reports
issues; it does not split, merge, renumber, repair, or rewrite the decision.

### 7. Generate the Reusable Runtime Script

```powershell
python -X utf8 cli.py generate "C:\path\to\manual.md"
```

The script is written to:

```text
FG/03_chunking/<script_stem>_chunking.py
```

For ordinary filenames, the script stem comes from the Markdown filename.
For generic names such as `structured.md`, the parent directory name is used
so several Stage 2 documents do not all produce `structured_chunking.py`.

## Running a Generated Strategy

The generated script requires a Markdown file or folder as its positional
`input_path`.

From the repository root:

```powershell
python -X utf8 FG\03_chunking\<strategy>_chunking.py `
  "C:\path\to\markdown_input"
```

### Write UTF-8 Text Chunk Files

Text is the default emission mode:

```powershell
python -X utf8 FG\03_chunking\<strategy>_chunking.py `
  "C:\path\to\markdown_input" `
  --output "C:\path\to\chunk_output"
```

Without `--output`, chunks are written under `./chunk_output` relative to the
current working directory.

For one input file, chunk filenames look like:

```text
<document_id>_chunk_001.txt
<document_id>_chunk_002.txt
```

For folder input, each source document normally gets its own output
subdirectory. Duplicate source stems are disambiguated using their relative
paths.

### Emit JSONL

```powershell
python -X utf8 FG\03_chunking\<strategy>_chunking.py `
  "C:\path\to\markdown_input" --emit jsonl |
  Set-Content -Encoding utf8 chunks.jsonl
```

Each `RuntimeChunk` record contains:

- `chunk_id`, `document_id`, and `chunk_index`;
- `unit_type` and `title`;
- `source_path`;
- start/end block IDs and line numbers;
- chunk `text`.

Runtime records are currently flat. Analysis boundary spans and unit metadata
inform the generated strategy, but `parent_identifier` relationships are not
learned into or emitted by the runtime script. `--leaf-only` is accepted for
compatibility and currently has no effect.

### Emit Qdrant-Shaped JSON

```powershell
python -X utf8 FG\03_chunking\<strategy>_chunking.py `
  "C:\path\to\markdown_input" --emit qdrant |
  Set-Content -Encoding utf8 qdrant_points.json
```

The command emits a JSON array with this shape:

```json
[
  {
    "id": "manual_chunk_001",
    "vector": null,
    "payload": {
      "chunk_id": "manual_chunk_001",
      "document_id": "manual",
      "unit_type": "section",
      "title": "Section heading",
      "source_path": "C:/path/to/manual.md",
      "start_block_id": "b0001",
      "end_block_id": "b0008",
      "start_line": 0,
      "end_line": 27,
      "text": "..."
    }
  }
]
```

`vector` is deliberately `null`. Generate embeddings and validate vector
dimensions before sending these records to Qdrant. This command does not
connect to or modify a Qdrant collection.

## Artifact Locations

| Artifact | Current location | Notes |
|---|---|---|
| Parsed blocks | `analysis/<doc_id>_blocks.json` | Refreshed from the current source |
| Document profile | `analysis/<doc_id>_profile.json` | Pydantic-validated LLM output |
| Boundary decision | `analysis/<doc_id>_decision.json` | Structural units and unresolved IDs |
| Human review | `analysis/<doc_id>_review.md` | Sorted by confidence |
| Repair backup | `analysis/<doc_id>_decision.backup-*.json` | Created before decision replacement |
| Generated strategy | `FG/03_chunking/<strategy>_chunking.py` | Reusable and LLM-free at runtime |
| Runtime text chunks | `<output>/<document_id>_chunk_*.txt` | Single-file runtime input |
| Folder runtime chunks | `<output>/<source-subdir>/<document_id>_chunk_*.txt` | One subdirectory per source document |

Files such as `output/structured_chunker.py`, `output/structured.jsonl`, and
`output/chunks.txt` are older generated examples. They do not represent the
current reusable strategy output path or command contract.

## Input and Decision Contracts

The Markdown loader produces these block types:

- `heading`
- `paragraph`
- `list_item`
- `code_block`
- `table`
- `blockquote`
- `hr`

Blocks receive positional IDs such as `b0001`, `b0002`, and `b0003` in source
order. A decision unit references a start and end block ID and can include a
unit type, identifier, title, parent identifier, language metadata,
confidence, boundary reason, and `needs_review`.

Because block IDs are positional, editing the source can change which content
an existing ID refers to. Re-run analysis and generation after changing the
sample Markdown.

## Programmatic Entry Point

`run_pipeline.py` exposes a Python function that returns blocks, profile,
decision, validation reports, chunks, and generated-script paths. It is not
currently identical to the CLI flow: its code-generation call does not pass
the full block/profile/decision learning metadata, so the generated strategy
falls back to more generic defaults.

Use `cli.py run` or `cli.py run-all` for the supported, fully learned strategy
workflow.

## Tests and Verification

The dependency file does not install `pytest`. The built-in smoke test can be
run without it:

```powershell
python -X utf8 -B tests\test_markdown_loader.py
```

With `pytest` installed:

```powershell
python -m pytest tests -v
```

Useful command-contract checks:

```powershell
python -X utf8 cli.py --help
python -X utf8 cli.py run-all --help
python -X utf8 ..\<strategy>_chunking.py --help
```

The current automated tests cover Markdown loading and candidate-boundary
detection. They do not cover live Ollama calls, CLI orchestration, repair,
validators, strategy generation, or generated-script runtime behavior.

## Known Limitations

- Analysis requires a working local Ollama model and valid structured JSON
  output from that model.
- Model responses are schema-validated. Apart from stripping an optional JSON
  code fence, invalid output fails loudly rather than retrying automatically.
- Folder learning over more than 10 files uses an unseeded random sample.
- Single-file analysis artifacts use the source stem as `doc_id`; analysing
  different files with the same stem can overwrite earlier artifacts.
- Runtime chunks are flat and do not retain analysis-time parent/child links.
- Qdrant emission contains no embeddings and performs no upsert.
- The generated runtime always applies generic legal/structural patterns in
  addition to learned hints; it is learned-hint guided, not purely learned.
- The current generated runtime skips the first detected boundary after block
  zero when building its initial span list. Inspect the first chunks closely
  until that implementation defect is fixed.
- `config/model.yaml` contains fields that are not yet wired into the current
  client or CLI, as listed in the configuration table above.
- Existing generated files remain unchanged when source code or Markdown
  changes. Re-run `generate` or `run-all` to refresh them.

## Troubleshooting

### Ollama Model Not Found

```powershell
ollama list
ollama pull qwen3:14b
```

Ensure the model name matches `config/model.yaml`.

### Ollama Connection Fails

Start Ollama and verify it responds before running `profile`, `analyze`,
`repair`, `run`, or `run-all`:

```powershell
ollama serve
```

The `model.host` YAML field is not currently wired into the client.

### Profile or Decision Is Missing

The explicit stage order is:

```text
load -> profile -> analyze -> validate -> generate
```

`analyze` requires the saved profile. `validate` and `generate` require the
saved decision. Use `run` when you want the normal sequence automatically.

### Hindi Output Raises a Console Encoding Error

Use UTF-8 mode:

```powershell
python -X utf8 cli.py run "C:\path\to\hindi.md"
python -X utf8 ..\<strategy>_chunking.py "C:\path\to\hindi.md"
```

### Review Shows Missing or Duplicate Blocks

Validation does not alter the decision. Inspect
`analysis/<doc_id>_review.md`, run a targeted `repair`, then run `validate`
and `generate` again.

## Package Layout

```text
md_guided_chunking/
|-- README.md
|-- requirements.txt
|-- cli.py                         # canonical CLI
|-- run_pipeline.py                # programmatic, not fully CLI-equivalent
|-- config/
|   |-- model.yaml
|   `-- prompts/
|       |-- document_profile.txt
|       |-- boundary_analysis.txt
|       `-- boundary_repair.txt
|-- ingestion/
|   `-- markdown_loader.py
|-- structure/
|   |-- candidate_detector.py
|   `-- window_builder.py
|-- llm/
|   |-- ollama_client.py
|   `-- schemas.py
|-- analysis/
|   |-- document_profiler.py
|   |-- boundary_analyser.py
|   |-- repair.py
|   `-- <generated analysis artifacts>
|-- validation/
|   |-- coverage_validator.py
|   |-- sequence_validator.py
|   `-- size_validator.py
|-- chunking/
|   `-- parent_child_builder.py
|-- codegen/
|   `-- script_generator.py
|-- output/                        # older generated examples
`-- tests/
    `-- test_markdown_loader.py
```
