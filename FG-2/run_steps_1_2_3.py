"""
Unified runner for CHiPPY steps 1, 2, and 3.

Steps covered:
1) 01_preprocessing/run_stage1.py + run_stage2.py
2) 02_optimization/optimize.py (+ optional spell correction via spellv2.py functions)
3) 03_chunking/docling_chunker.py

Usage:
    python run_steps_1_2_3.py
    python run_steps_1_2_3.py --input-pdfs ./01_preprocessing/input_pdfs
    python run_steps_1_2_3.py --use-spell --dict-path ./02_optimization/dict/hi_dict_2_updated.txt
    python run_steps_1_2_3.py --skip-stage1 --skip-stage2 --skip-stage3
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType


def load_module(module_name: str, module_path: Path) -> ModuleType:
    """Load a Python module from a file path."""
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from: {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_command(cmd: list[str], label: str) -> None:
    """Run a subprocess command and fail fast on non-zero exit."""
    print(f"\n>>> {label}")
    print("$ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def collect_structured_markdown(stage2_output: Path) -> list[Path]:
    """Find all structured.md files produced by stage 2 OCR."""
    files = sorted(stage2_output.rglob("structured.md"))
    return [f for f in files if f.is_file()]


def optimize_documents(
    optimize_module: ModuleType,
    source_files: list[Path],
    output_dir: Path,
) -> list[Path]:
    """Run optimize.py on all stage2 OCR markdown files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    optimized_files: list[Path] = []

    print(f"\n>>> Optimization: processing {len(source_files)} file(s)")
    for src in source_files:
        doc_name = src.parent.name
        dst = output_dir / f"{doc_name}.md"
        optimize_module.optimize_file(str(src), str(dst))
        optimized_files.append(dst)

    return optimized_files


def spell_correct_documents(
    spell_module: ModuleType,
    input_files: list[Path],
    output_dir: Path,
    dict_path: Path,
    update_dictionary: bool,
) -> list[Path]:
    """Apply spell correction using spellv2 logic without hardcoded paths."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if not dict_path.exists():
        raise FileNotFoundError(f"Dictionary not found: {dict_path}")

    freq_dict = spell_module.load_dict(str(dict_path))
    sym = spell_module.build_symspell(freq_dict)

    corrected_files: list[Path] = []
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n>>> Spell correction: processing {len(input_files)} file(s)")
    for src in input_files:
        lines = src.read_text(encoding="utf-8").splitlines(keepends=True)
        log_lines: list[str] = []
        corrected_lines: list[str] = []
        all_words: list[str] = []

        for line in lines:
            fixed, words = spell_module.correct_line(line, sym, freq_dict, log_lines)
            corrected_lines.append(fixed)
            all_words.extend(words)

        dst = src
        dst.write_text("".join(corrected_lines), encoding="utf-8")
        corrected_files.append(dst)

        log_path = logs_dir / f"{src.stem}_spell_log.txt"
        log_path.write_text("\n".join(log_lines), encoding="utf-8")

        if update_dictionary:
            freq_dict = spell_module.update_frequencies(freq_dict, all_words)

    if update_dictionary:
        spell_module.save_dict(freq_dict, str(dict_path))

    return corrected_files


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CHiPPY steps 1, 2, 3 from one file")

    root_default = Path(__file__).resolve().parent

    parser.add_argument("--root", type=str, default=str(root_default), help="CHiPPY root directory")

    parser.add_argument("--input-pdfs", type=str, default="", help="Input PDF file/folder for stage 1")
    parser.add_argument("--stage1-output", type=str, default="01_preprocessing/stage1_output")
    parser.add_argument("--stage2-output", type=str, default="01_preprocessing/stage2_output")

    parser.add_argument("--optimization-output", type=str, default="02_optimization/output")
    parser.add_argument("--chunk-output", type=str, default="03_chunking/output")
    parser.add_argument("--chunk-pattern", type=str, default="*.md")
    parser.add_argument("--mapping", type=str, default="", help="Optional mapping file for chunker")

    parser.add_argument("--use-spell", action="store_true", help="Apply spell correction after optimize")
    parser.add_argument(
        "--dict-path",
        type=str,
        default="02_optimization/dict/hi_dict_2_updated.txt",
        help="Dictionary path for spell correction",
    )
    parser.add_argument(
        "--update-dictionary",
        action="store_true",
        help="Update dictionary frequencies while spell-correcting",
    )

    parser.add_argument("--skip-stage1", action="store_true", help="Skip preprocessing stage 1 (image prep)")
    parser.add_argument("--skip-stage2", action="store_true", help="Skip preprocessing stage 2 (OCR)")
    parser.add_argument("--skip-stage3", action="store_true", help="Skip chunking stage")

    args = parser.parse_args()

    root = Path(args.root).resolve()
    python_exe = sys.executable

    run_stage1_script = root / "01_preprocessing" / "run_stage1.py"
    run_stage2_script = root / "01_preprocessing" / "run_stage2.py"
    optimize_script = root / "02_optimization" / "optimize.py"
    spell_script = root / "02_optimization" / "spellv2.py"
    chunker_script = root / "03_chunking" / "docling_chunker.py"

    stage1_output = (root / args.stage1_output).resolve()
    stage2_output = (root / args.stage2_output).resolve()
    optimization_output = (root / args.optimization_output).resolve()
    chunk_output = (root / args.chunk_output).resolve()
    dict_path = (root / args.dict_path).resolve()

    # Step 1: run stage1
    if not args.skip_stage1:
        cmd = [python_exe, str(run_stage1_script), "-o", str(stage1_output)]
        if args.input_pdfs:
            cmd.insert(2, str(Path(args.input_pdfs).resolve()))
        run_command(cmd, "Step 1A - Preprocessing (run_stage1.py)")

    # Step 2: run stage2
    if not args.skip_stage2:
        cmd = [
            python_exe,
            str(run_stage2_script),
            str(stage1_output),
            "-o",
            str(stage2_output),
        ]
        run_command(cmd, "Step 1B - OCR extraction (run_stage2.py)")

    # Step 2 optimization
    structured_files = collect_structured_markdown(stage2_output)
    if not structured_files:
        raise FileNotFoundError(f"No structured.md files found in {stage2_output}")

    optimize_module = load_module("chippy_optimize", optimize_script)
    optimized_files = optimize_documents(optimize_module, structured_files, optimization_output)

    if args.use_spell:
        spell_module = load_module("chippy_spell", spell_script)
        optimized_files = spell_correct_documents(
            spell_module=spell_module,
            input_files=optimized_files,
            output_dir=optimization_output,
            dict_path=dict_path,
            update_dictionary=args.update_dictionary,
        )

    # Step 3 chunking
    if not args.skip_stage3:
        cmd = [
            python_exe,
            str(chunker_script),
            "--input",
            str(optimization_output),
            "--output",
            str(chunk_output),
            "--pattern",
            args.chunk_pattern,
        ]
        if args.mapping:
            cmd.extend(["--mapping", str(Path(args.mapping).resolve())])

        run_command(cmd, "Step 3 - Chunking (docling_chunker.py)")

    print("\nDone: unified steps 1, 2, 3 execution completed.")


if __name__ == "__main__":
    main()
