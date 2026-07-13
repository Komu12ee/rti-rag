"""Minimal smoke tests for the markdown loader and candidate detector.
Run with: python -m pytest tests/ -v  (or just: python tests/test_markdown_loader.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingestion.markdown_loader import load_markdown_blocks
from structure.candidate_detector import detect_candidate_boundaries, build_heading_outline

SAMPLE_MD = """\
# Title

Intro paragraph here.

## Section 1

1. First point
2. Second point

## Section 2

| A | B |
|---|---|
| 1 | 2 |

```python
print("hello")
```

> A quote block

---

Final paragraph.
"""


def test_headings_detected(tmp_path):
    p = tmp_path / "sample.md"
    p.write_text(SAMPLE_MD, encoding="utf-8")
    blocks = load_markdown_blocks(p)
    headings = [b for b in blocks if b.block_type == "heading"]
    assert len(headings) == 3
    assert headings[0].heading_level == 1
    assert headings[1].heading_level == 2


def test_all_block_types_present(tmp_path):
    p = tmp_path / "sample.md"
    p.write_text(SAMPLE_MD, encoding="utf-8")
    blocks = load_markdown_blocks(p)
    types = {b.block_type for b in blocks}
    assert "heading" in types
    assert "paragraph" in types
    assert "list_item" in types
    assert "table" in types
    assert "code_block" in types
    assert "blockquote" in types
    assert "hr" in types


def test_block_ids_are_sequential_and_unique(tmp_path):
    p = tmp_path / "sample.md"
    p.write_text(SAMPLE_MD, encoding="utf-8")
    blocks = load_markdown_blocks(p)
    ids = [b.block_id for b in blocks]
    assert len(ids) == len(set(ids)), "block ids must be unique"
    assert ids == sorted(ids), "block ids should be in document order"


def test_candidate_boundaries_include_headings(tmp_path):
    p = tmp_path / "sample.md"
    p.write_text(SAMPLE_MD, encoding="utf-8")
    blocks = load_markdown_blocks(p)
    candidates = detect_candidate_boundaries(blocks)
    candidate_ids = {c.block_id for c in candidates}
    heading_ids = {b.block_id for b in blocks if b.block_type == "heading"}
    assert heading_ids.issubset(candidate_ids)


def test_heading_outline(tmp_path):
    p = tmp_path / "sample.md"
    p.write_text(SAMPLE_MD, encoding="utf-8")
    blocks = load_markdown_blocks(p)
    outline = build_heading_outline(blocks)
    assert [o["text"] for o in outline] == ["Title", "Section 1", "Section 2"]


if __name__ == "__main__":
    import tempfile
    class _TmpPath:
        def __init__(self, base): self.base = Path(base)
        def __truediv__(self, name): return self.base / name

    with tempfile.TemporaryDirectory() as d:
        tmp = _TmpPath(d)
        test_headings_detected(tmp)
        test_all_block_types_present(tmp)
        test_block_ids_are_sequential_and_unique(tmp)
        test_candidate_boundaries_include_headings(tmp)
        test_heading_outline(tmp)
    print("All smoke tests passed.")
