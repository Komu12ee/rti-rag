"""
Programmatic entrypoint, for use from other Python code instead of the
CLI. Mirrors `cli.py run` (load -> profile -> analyze -> validate ->
generate) but returns the objects directly instead of just printing.

Repair is intentionally NOT part of this function - call
`analysis.repair.repair_region` yourself, explicitly, if/when you decide
a region needs it.
"""
from __future__ import annotations

from pathlib import Path

from ingestion.markdown_loader import load_markdown_blocks
from llm.ollama_client import OllamaStructuredClient
from analysis.document_profiler import build_document_profile
from analysis.boundary_analyser import analyse_boundaries, save_decision, write_review_report
from validation.coverage_validator import check_coverage
from validation.sequence_validator import check_ordering
from validation.size_validator import check_sizes
from chunking.parent_child_builder import build_chunks
from codegen.script_generator import write_chunker_script


def run_pipeline(
    md_file: str,
    window_size: int = 30,
    window_overlap: int = 3,
    analysis_dir: str = "analysis",
    output_dir: str = "output",
):
    doc_id = Path(md_file).stem.replace("-", "_").replace(" ", "_")
    analysis_path = Path(analysis_dir)
    analysis_path.mkdir(parents=True, exist_ok=True)

    blocks = load_markdown_blocks(md_file)

    client = OllamaStructuredClient()
    profile = build_document_profile(Path(md_file).name, blocks, client=client)
    (analysis_path / f"{doc_id}_profile.json").write_text(
        profile.model_dump_json(indent=2), encoding="utf-8"
    )

    decision = analyse_boundaries(
        blocks, profile, window_size=window_size,
        context_overlap=window_overlap, client=client,
    )
    decision_path = analysis_path / f"{doc_id}_decision.json"
    save_decision(decision, decision_path)
    review_path = analysis_path / f"{doc_id}_review.md"
    write_review_report(decision, review_path)

    coverage = check_coverage(blocks, decision)
    ordering = check_ordering(blocks, decision)
    sizes = check_sizes(blocks, decision)

    chunks = build_chunks(blocks, decision, document_id=doc_id)
    script_path = write_chunker_script(
        chunks, doc_id, Path(md_file).name, output_dir=output_dir
    )

    return {
        "doc_id": doc_id,
        "blocks": blocks,
        "profile": profile,
        "decision": decision,
        "decision_path": decision_path,
        "review_path": review_path,
        "coverage": coverage,
        "ordering": ordering,
        "sizes": sizes,
        "chunks": chunks,
        "script_path": script_path,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("usage: python run_pipeline.py <file.md>")
        raise SystemExit(1)
    result = run_pipeline(sys.argv[1])
    print(f"Generated: {result['script_path']}")
    print(f"Review report: {result['review_path']}")
