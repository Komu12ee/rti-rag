"""Default output folder naming shared by preprocessing entry points."""
from __future__ import annotations

from pathlib import Path


def _clean_input_name(input_path: Path) -> str:
    path = Path(input_path)
    if path.is_file():
        return path.stem
    return path.name or path.resolve().name


def output_dir_for_pdf_input(input_path: str | Path, stage: str) -> Path:
    """Return `<input-name>_<stage>_output` next to the PDF input path."""
    path = Path(input_path)
    base_dir = path.parent if path.is_file() else path.parent
    input_name = _clean_input_name(path)
    return base_dir / f"{input_name}_{stage}_output"


def stage2_output_dir_for_stage1_input(input_path: str | Path) -> Path:
    """Map a Stage 1 input/root to its matching Stage 2 output root."""
    path = Path(input_path)
    name = path.name
    if name.endswith("_stage1_output"):
        return path.with_name(f"{name[:-14]}_stage2_output")
    if path.parent.name.endswith("_stage1_output"):
        stage1_root = path.parent
        return stage1_root.with_name(f"{stage1_root.name[:-14]}_stage2_output")
    return output_dir_for_pdf_input(path, "stage2")
