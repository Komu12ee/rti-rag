"""
CLI entrypoint. Every pipeline stage is still available as an explicit
subcommand, and `repair` remains manual-only.

Use `python cli.py run-all <input_path>` for the practical one-command flow:
load -> profile -> analyze -> validate -> generate -> review.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

from ingestion.markdown_loader import DocumentBlock, blocks_to_dicts, load_markdown_blocks
from llm.ollama_client import OllamaStructuredClient
from llm.schemas import ChunkingDecision, DocumentProfile
from analysis.document_profiler import build_document_profile
from analysis.boundary_analyser import (
    analyse_boundaries, load_decision, save_decision, write_review_report,
)
from analysis.repair import (
    backup_decision_file, find_unit_by_identifier, merge_repair_into_decision,
    repair_region,
)
from validation.coverage_validator import CoverageReport, check_coverage
from validation.sequence_validator import SequenceReport, check_ordering
from validation.size_validator import SizeReport, check_sizes
from chunking.parent_child_builder import build_chunks
from codegen.script_generator import write_chunker_script, write_strategy_chunker_script


PROJECT_DIR = Path(__file__).resolve().parent
ANALYSIS_DIR = PROJECT_DIR / "analysis"
OUTPUT_DIR = PROJECT_DIR / "output"
GENERIC_FILE_STEMS = {
    "structured", "document", "documents", "content", "output", "stage2", "merged",
}


def _repo_root() -> Path:
    for candidate in (PROJECT_DIR, *PROJECT_DIR.parents):
        if (candidate / ".git").exists() or (candidate / "FG").is_dir():
            return candidate
    return PROJECT_DIR


def _chunking_output_dir() -> Path:
    return _repo_root() / "FG" / "03_chunking"


def _resolve_input_path(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.exists():
        return candidate.resolve()
    if candidate.is_absolute():
        return candidate

    for base in (_repo_root(), PROJECT_DIR):
        resolved = base / candidate
        if resolved.exists():
            return resolved.resolve()

    return candidate.resolve()


def _require_markdown_file(raw_path: str) -> Path:
    path = _resolve_input_path(raw_path)
    if not path.exists():
        print(f"Input file does not exist: {path}", file=sys.stderr)
        raise SystemExit(1)
    if not path.is_file() or path.suffix.lower() != ".md":
        print(f"Input must be a .md file: {path}", file=sys.stderr)
        raise SystemExit(1)
    return path


def _safe_name(value: str) -> str:
    chars: list[str] = []
    for ch in value:
        if ch.isalnum() or ch in {"_", "-"}:
            chars.append(ch)
        elif chars and chars[-1] != "_":
            chars.append("_")
    return "".join(chars).strip("_") or "document"


def _doc_id(md_path: str | Path) -> str:
    return _safe_name(Path(md_path).stem).replace("-", "_")


def _script_stem_for_input(input_path: Path) -> str:
    if input_path.is_dir():
        return _safe_name(input_path.name)
    if input_path.stem.lower() in GENERIC_FILE_STEMS and input_path.parent.name:
        return _safe_name(input_path.parent.name)
    return _safe_name(input_path.stem)


def _sample_doc_id(md_path: Path, input_root: Path | None) -> str:
    if input_root and input_root.is_dir():
        try:
            relative = md_path.relative_to(input_root).with_suffix("")
            return _safe_name(f"{input_root.name}_{'_'.join(relative.parts)}").replace("-", "_")
        except ValueError:
            pass
    return _doc_id(md_path)


def _dedupe_doc_id(doc_id: str, used: set[str]) -> str:
    candidate = doc_id
    suffix = 2
    while candidate in used:
        candidate = f"{doc_id}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _blocks_path(doc_id: str) -> Path:
    return ANALYSIS_DIR / f"{doc_id}_blocks.json"


def _profile_path(doc_id: str) -> Path:
    return ANALYSIS_DIR / f"{doc_id}_profile.json"


def _decision_path(doc_id: str) -> Path:
    return ANALYSIS_DIR / f"{doc_id}_decision.json"


def _review_path(doc_id: str) -> Path:
    return ANALYSIS_DIR / f"{doc_id}_review.md"


def _load_blocks_cached_or_fresh(md_path: str | Path, doc_id: str) -> list[DocumentBlock]:
    # Blocks are cheap to regenerate and content-addressed by nature of
    # the source file, so we always re-parse fresh rather than trusting a
    # cache that might be stale relative to the .md file.
    blocks = load_markdown_blocks(md_path)
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    _blocks_path(doc_id).write_text(
        json.dumps(blocks_to_dicts(blocks), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return blocks


def _load_profile_if_present(doc_id: str) -> DocumentProfile | None:
    profile_path = _profile_path(doc_id)
    if not profile_path.exists():
        return None
    return DocumentProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))


def _validation_reports(
    blocks: list[DocumentBlock],
    decision: ChunkingDecision,
) -> tuple[CoverageReport, SequenceReport, SizeReport]:
    return (
        check_coverage(blocks, decision),
        check_ordering(blocks, decision),
        check_sizes(blocks, decision),
    )


def _print_validation_reports(
    coverage: CoverageReport,
    ordering: SequenceReport,
    sizes: SizeReport,
) -> None:
    print("=== Coverage ===")
    print(f"Total blocks: {coverage.total_blocks}, covered: {coverage.covered_blocks}")
    if coverage.missing_block_ids:
        print(f"MISSING ({len(coverage.missing_block_ids)}): {coverage.missing_block_ids}")
    if coverage.duplicate_block_ids:
        print(f"DUPLICATED ({len(coverage.duplicate_block_ids)}): "
              f"{coverage.duplicate_block_ids}")
    print("OK" if coverage.ok else "ISSUES FOUND (see above)")

    print("\n=== Ordering / Sequence ===")
    if ordering.out_of_order:
        print(f"Out of order pairs: {ordering.out_of_order}")
    if ordering.numbering_gaps:
        print("Numbering gaps:")
        for gap in ordering.numbering_gaps:
            print(f"  - {gap}")
    print("OK" if ordering.ok else "ISSUES FOUND (see above) - warnings only, "
          "nothing auto-fixed")

    print("\n=== Size ===")
    if sizes.flags:
        for flag in sizes.flags:
            print(f"  {flag.flag}: {flag.identifier} ({flag.unit_type}) "
                  f"~{flag.approx_tokens} tokens")
    print("OK" if sizes.ok else "FLAGS FOUND (see above) - informational only")


def _markdown_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() == ".md" else []
    return sorted(
        (path for path in input_path.rglob("*.md") if path.is_file()),
        key=lambda path: str(path).casefold(),
    )


def _sample_markdown_files(files: list[Path]) -> list[Path]:
    if len(files) <= 10:
        return files
    sample_count = random.randint(5, 10)
    return sorted(random.sample(files, sample_count), key=lambda path: str(path).casefold())


def _run_normal_pipeline_for_file(
    md_path: Path,
    doc_id: str,
    window_size: int,
    window_overlap: int,
) -> dict[str, Any]:
    print(f"\n[load] {md_path}")
    blocks = _load_blocks_cached_or_fresh(md_path, doc_id)
    print(f"Loaded {len(blocks)} blocks")
    print(f"Written: {_blocks_path(doc_id)}")

    print("[profile]")
    client = OllamaStructuredClient()
    profile = build_document_profile(md_path.name, blocks, client=client)
    _profile_path(doc_id).write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    print(f"Document profile written to {_profile_path(doc_id)}")

    print("[analyze]")
    decision = analyse_boundaries(
        blocks,
        profile,
        window_size=window_size,
        context_overlap=window_overlap,
        client=client,
    )
    save_decision(decision, _decision_path(doc_id))
    write_review_report(decision, _review_path(doc_id))
    print(f"Decision written to {_decision_path(doc_id)}")
    print(f"Review report written to {_review_path(doc_id)}")
    print(f"Units found: {len(decision.units)}, "
          f"unresolved blocks: {len(decision.unresolved_block_ids)}")

    print("[validate]")
    coverage, ordering, sizes = _validation_reports(blocks, decision)
    _print_validation_reports(coverage, ordering, sizes)

    chunks = build_chunks(blocks, decision, document_id=doc_id)
    return {
        "document_id": doc_id,
        "source_filename": md_path.name,
        "source_path": str(md_path),
        "blocks": blocks,
        "profile": profile,
        "decision": decision,
        "coverage": coverage,
        "ordering": ordering,
        "sizes": sizes,
        "chunks": chunks,
        "review_path": _review_path(doc_id),
    }


def cmd_load(args) -> None:
    md_path = _require_markdown_file(args.md_file)
    doc_id = _doc_id(md_path)
    blocks = _load_blocks_cached_or_fresh(md_path, doc_id)
    print(f"Loaded {len(blocks)} blocks from {md_path}")
    print(f"Written: {_blocks_path(doc_id)}")


def cmd_profile(args) -> None:
    md_path = _require_markdown_file(args.md_file)
    doc_id = _doc_id(md_path)
    blocks = _load_blocks_cached_or_fresh(md_path, doc_id)
    client = OllamaStructuredClient()
    profile = build_document_profile(md_path.name, blocks, client=client)
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    _profile_path(doc_id).write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    print(f"Document profile written to {_profile_path(doc_id)}")
    print(profile.model_dump_json(indent=2))


def cmd_analyze(args) -> None:
    md_path = _require_markdown_file(args.md_file)
    doc_id = _doc_id(md_path)
    blocks = _load_blocks_cached_or_fresh(md_path, doc_id)

    profile_path = _profile_path(doc_id)
    if not profile_path.exists():
        print("No profile found - run `cli.py profile` first.", file=sys.stderr)
        raise SystemExit(1)
    profile = DocumentProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))

    client = OllamaStructuredClient()
    decision = analyse_boundaries(
        blocks,
        profile,
        window_size=args.window_size,
        context_overlap=args.window_overlap,
        client=client,
    )
    save_decision(decision, _decision_path(doc_id))
    write_review_report(decision, _review_path(doc_id))
    print(f"Decision written to {_decision_path(doc_id)}")
    print(f"Review report written to {_review_path(doc_id)}")
    print(f"Units found: {len(decision.units)}, "
          f"unresolved blocks: {len(decision.unresolved_block_ids)}")


def cmd_review(args) -> None:
    md_path = _require_markdown_file(args.md_file)
    doc_id = _doc_id(md_path)
    review_path = _review_path(doc_id)
    if not review_path.exists():
        print("No review report found - run `cli.py analyze` first.", file=sys.stderr)
        raise SystemExit(1)
    print(review_path.read_text(encoding="utf-8"))


def cmd_repair(args) -> None:
    md_path = _require_markdown_file(args.md_file)
    doc_id = _doc_id(md_path)
    blocks = _load_blocks_cached_or_fresh(md_path, doc_id)

    profile_path = _profile_path(doc_id)
    decision_path = _decision_path(doc_id)
    if not profile_path.exists() or not decision_path.exists():
        print("Need both a profile and a decision before repairing - run "
              "`cli.py profile` and `cli.py analyze` first.", file=sys.stderr)
        raise SystemExit(1)

    profile = DocumentProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    decision = load_decision(decision_path)

    if args.unit_id:
        unit = find_unit_by_identifier(decision, args.unit_id)
        if unit is None:
            print(f"No unit with identifier '{args.unit_id}' found in the "
                  f"current decision. Check {_review_path(doc_id)} for valid "
                  f"identifiers, or use --block-range instead.", file=sys.stderr)
            raise SystemExit(1)
        start_id, end_id = unit.start_block_id, unit.end_block_id
    elif args.block_range:
        try:
            start_id, end_id = args.block_range.split(":")
        except ValueError:
            print("--block-range must be START_ID:END_ID", file=sys.stderr)
            raise SystemExit(1)
    else:
        print("Specify --unit-id or --block-range to target a repair.", file=sys.stderr)
        raise SystemExit(1)

    client = OllamaStructuredClient()
    result = repair_region(
        blocks,
        profile,
        decision,
        start_block_id=start_id,
        end_block_id=end_id,
        repair_reason=args.reason or "",
        context_blocks=args.context_blocks,
        client=client,
    )

    print("Repair result:")
    print(result.model_dump_json(indent=2))

    backup = backup_decision_file(decision_path)
    if backup != decision_path:
        print(f"Backed up previous decision to {backup}")

    merged = merge_repair_into_decision(decision, result, start_id, end_id, blocks)
    save_decision(merged, decision_path)
    write_review_report(merged, _review_path(doc_id))
    print(f"Decision updated: {decision_path}")
    print(f"Review report updated: {_review_path(doc_id)}")


def cmd_validate(args) -> None:
    md_path = _require_markdown_file(args.md_file)
    doc_id = _doc_id(md_path)
    blocks = _load_blocks_cached_or_fresh(md_path, doc_id)
    decision_path = _decision_path(doc_id)
    if not decision_path.exists():
        print("No decision found - run `cli.py analyze` first.", file=sys.stderr)
        raise SystemExit(1)
    decision = load_decision(decision_path)

    coverage, ordering, sizes = _validation_reports(blocks, decision)
    _print_validation_reports(coverage, ordering, sizes)


def cmd_generate(args) -> None:
    md_path = _require_markdown_file(args.md_file)
    doc_id = _doc_id(md_path)
    blocks = _load_blocks_cached_or_fresh(md_path, doc_id)
    decision_path = _decision_path(doc_id)
    if not decision_path.exists():
        print("No decision found - run `cli.py analyze` first.", file=sys.stderr)
        raise SystemExit(1)
    decision = load_decision(decision_path)
    profile = _load_profile_if_present(doc_id)

    chunks = build_chunks(blocks, decision, document_id=doc_id)
    output_path = write_chunker_script(
        chunks,
        doc_id,
        str(md_path),
        output_dir=_chunking_output_dir(),
        script_stem=_script_stem_for_input(md_path),
        blocks=blocks,
        decision=decision,
        profile=profile,
    )
    print(f"Generated reusable chunking script: {output_path}")
    print(f"Chunks learned from this sample: {len(chunks)} total, "
          f"{len([c for c in chunks if c.is_parent])} parents, "
          f"{len([c for c in chunks if c.parent_id])} children")
    print(f"Run it with: python {output_path} {md_path} --output "
          f"{_chunking_output_dir() / (_script_stem_for_input(md_path) + '_chunks')}")


def cmd_run(args) -> None:
    """One-shot convenience for a single .md file. Never calls repair."""
    cmd_load(args)
    cmd_profile(args)
    cmd_analyze(args)
    cmd_validate(args)
    cmd_generate(args)
    cmd_review(args)


def cmd_run_all(args) -> None:
    input_path = _resolve_input_path(args.input_path)
    if not input_path.exists():
        print(f"Input path does not exist: {input_path}", file=sys.stderr)
        raise SystemExit(1)

    if input_path.is_file() and input_path.suffix.lower() != ".md":
        print(f"Input file must be a .md file: {input_path}", file=sys.stderr)
        raise SystemExit(1)

    md_files = _markdown_files(input_path)
    if not md_files:
        print(f"No Markdown files found under: {input_path}", file=sys.stderr)
        raise SystemExit(1)

    samples = _sample_markdown_files(md_files) if input_path.is_dir() else md_files
    if input_path.is_dir():
        print(f"Folder input: found {len(md_files)} Markdown files")
        print(f"Representative sample: {len(samples)} file(s)")
        for sample in samples:
            print(f"  - {sample}")

    used_doc_ids: set[str] = set()
    sample_records: list[dict[str, Any]] = []
    for md_path in samples:
        raw_doc_id = _sample_doc_id(md_path, input_path if input_path.is_dir() else None)
        doc_id = _dedupe_doc_id(raw_doc_id, used_doc_ids)
        sample_records.append(
            _run_normal_pipeline_for_file(
                md_path=md_path,
                doc_id=doc_id,
                window_size=args.window_size,
                window_overlap=args.window_overlap,
            )
        )

    print("\n[generate]")
    script_stem = _script_stem_for_input(input_path)
    script_path = write_strategy_chunker_script(
        samples=sample_records,
        script_stem=script_stem,
        source_label=str(input_path),
        output_dir=_chunking_output_dir(),
    )
    print(f"Generated reusable chunking script: {script_path}")
    print(f"Run it with: python {script_path} {input_path}")
    print(f"Default chunk output: {Path.cwd() / 'chunk_output'}")

    print("\n[review]")
    if len(sample_records) == 1:
        review_path = sample_records[0]["review_path"]
        print(Path(review_path).read_text(encoding="utf-8"))
    else:
        print("Review reports for sampled files:")
        for record in sample_records:
            print(f"  - {record['review_path']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Markdown-guided chunking pipeline with manual-only "
                    "repair control.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_load = sub.add_parser("load", help="Parse the .md file into blocks (no LLM call).")
    p_load.add_argument("md_file")
    p_load.set_defaults(func=cmd_load)

    p_profile = sub.add_parser("profile", help="Stage 1 / Pass 1: build the document profile.")
    p_profile.add_argument("md_file")
    p_profile.set_defaults(func=cmd_profile)

    p_analyze = sub.add_parser("analyze", help="Stage 1 / Pass 2: boundary analysis.")
    p_analyze.add_argument("md_file")
    p_analyze.add_argument("--window-size", type=int, default=30)
    p_analyze.add_argument("--window-overlap", type=int, default=3)
    p_analyze.set_defaults(func=cmd_analyze)

    p_review = sub.add_parser("review", help="Print the human review report.")
    p_review.add_argument("md_file")
    p_review.set_defaults(func=cmd_review)

    p_repair = sub.add_parser(
        "repair",
        help="Manually trigger a repair pass over a specific unit or block range. "
             "Never called automatically by any other command.",
    )
    p_repair.add_argument("md_file")
    p_repair.add_argument("--unit-id", help="Identifier of the unit to repair "
                                            "(as shown in the review report).")
    p_repair.add_argument("--block-range", help="START_BLOCK_ID:END_BLOCK_ID "
                                                "to repair a raw range instead.")
    p_repair.add_argument("--reason", default="", help="Optional note on why "
                                                       "you're repairing this region.")
    p_repair.add_argument("--context-blocks", type=int, default=6)
    p_repair.set_defaults(func=cmd_repair)

    p_validate = sub.add_parser("validate", help="Run coverage/order/size checks (report only).")
    p_validate.add_argument("md_file")
    p_validate.set_defaults(func=cmd_validate)

    p_generate = sub.add_parser(
        "generate", help="Stage 2: generate the reusable standalone chunking script."
    )
    p_generate.add_argument("md_file")
    p_generate.set_defaults(func=cmd_generate)

    p_run = sub.add_parser(
        "run",
        help="Single-file convenience: load -> profile -> analyze -> validate -> "
             "generate -> review. Never triggers repair automatically.",
    )
    p_run.add_argument("md_file")
    p_run.add_argument("--window-size", type=int, default=30)
    p_run.add_argument("--window-overlap", type=int, default=3)
    p_run.set_defaults(func=cmd_run)

    p_run_all = sub.add_parser(
        "run-all",
        help="Run the full normal pipeline for a .md file or sampled Markdown folder. "
             "Never triggers repair automatically.",
    )
    p_run_all.add_argument("input_path")
    p_run_all.add_argument("--window-size", type=int, default=30)
    p_run_all.add_argument("--window-overlap", type=int, default=3)
    p_run_all.set_defaults(func=cmd_run_all)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
