"""
Structured-output schemas for the local LLM calls.

Note: `confidence` and `needs_review` are surfaced for YOU to read in the
review report. Nothing in this codebase auto-branches on their values -
see analysis/boundary_analyser.py and analysis/repair.py, which only
ever run when explicitly invoked from the CLI.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class DocumentProfile(BaseModel):
    document_type: Literal[
        "statute", "rules", "notification", "circular",
        "government_order", "judgment", "manual", "readme",
        "technical_spec", "notes", "form_collection",
        "mixed", "other",
    ]
    languages: list[str] = Field(default_factory=lambda: ["en"])
    hierarchy: list[str] = Field(
        default_factory=list,
        description="Ordered list of structural level names observed, "
                    "e.g. ['chapter','section','subsection']",
    )
    expected_unit_types: list[str] = Field(default_factory=list)
    numbering_patterns: list[str] = Field(default_factory=list)
    special_observations: list[str] = Field(default_factory=list)


class BlockRange(BaseModel):
    start_block_id: str
    end_block_id: str


class LanguageRange(BaseModel):
    language: Literal["hi", "en", "mixed", "other"]
    ranges: list[BlockRange] = Field(default_factory=list)


class StructuralUnit(BaseModel):
    unit_type: Literal[
        "part", "chapter", "section", "subsection", "clause",
        "rule", "subrule", "notification", "government_order",
        "circular", "judgment", "schedule", "annexure", "form",
        "table", "heading_group", "other",
    ]

    identifier: Optional[str] = None
    title: Optional[str] = None

    start_block_id: str
    end_block_id: str

    parent_identifier: Optional[str] = None
    language_mode: Literal["single", "bilingual", "mixed", "other"] = "single"
    language_ranges: list[LanguageRange] = Field(default_factory=list)

    confidence: float = Field(ge=0.0, le=1.0)
    boundary_reason: str
    needs_review: bool = False


class ChunkingDecision(BaseModel):
    document_type: str
    units: list[StructuralUnit] = Field(default_factory=list)
    unresolved_block_ids: list[str] = Field(default_factory=list)


class RepairResult(BaseModel):
    """Output of a manually-triggered repair pass over one region."""
    units: list[StructuralUnit] = Field(default_factory=list)
    unresolved_block_ids: list[str] = Field(default_factory=list)
    repair_notes: str = ""
