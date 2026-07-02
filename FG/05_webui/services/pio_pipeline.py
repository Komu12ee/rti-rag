from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from services.llm_provider import LLMProviderError, generate_text


# Expected layout:
#   FG/
#     rti_act_2005_sections_definitions.json
#     05_webui/
#       services/
#         pio_pipeline.py  <-- this file
WEBUI_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEBUI_DIR.parent

ACT_FILENAME = "rti_act_2005_sections_definitions.json"
PRECEDENT_PROMPT = (
    "Would you like to add relevant CIC and CG SIC decision references?\n"
    "Type Yes or OK to continue."
)
ADVISORY_REPORT_HEADING = "## PIO Advisory Report"

RTI_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "case_type",
        "language",
        "public_authority",
        "applicant_name",
        "application_reference",
        "submission_date",
        "period",
        "information_points",
        "extraction_uncertainties",
    ],
    "properties": {
        "case_type": {
            "type": "string",
            "enum": ["rti_application"],
        },
        "language": {
            "type": ["string", "null"],
        },
        "public_authority": {
            "type": ["string", "null"],
        },
        "applicant_name": {
            "type": ["string", "null"],
        },
        "application_reference": {
            "type": ["string", "null"],
        },
        "submission_date": {
            "type": ["string", "null"],
        },
        "period": {
            "type": "object",
            "additionalProperties": False,
            "required": ["from", "to"],
            "properties": {
                "from": {"type": ["string", "null"]},
                "to": {"type": ["string", "null"]},
            },
        },
        "information_points": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "point_no",
                    "requested_information",
                    "record_types_requested",
                    "source_span",
                ],
                "properties": {
                    "point_no": {"type": "integer"},
                    "requested_information": {"type": "string"},
                    "record_types_requested": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "source_span": {
                        "type": ["string", "null"],
                    },
                },
            },
        },
        "extraction_uncertainties": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


LEGAL_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "case_level_checks",
        "point_analysis",
        "mandatory_response_elements",
        "human_review_required",
    ],
    "properties": {
        "case_level_checks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "check",
                    "status",
                    "legal_basis",
                ],
                "properties": {
                    "check": {"type": "string"},
                    "status": {"type": "string"},
                    "legal_basis": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "point_analysis": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "point_no",
                    "request_type",
                    "record_status",
                    "possible_action",
                    "applicable_provisions",
                    "legal_reasoning",
                    "pio_verification_required",
                    "risk_flags",
                    "recommended_response_path",
                ],
                "properties": {
                    "point_no": {"type": "integer"},
                    "request_type": {"type": "string"},
                    "record_status": {"type": "string"},
                    "possible_action": {"type": "string"},
                    "applicable_provisions": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "legal_reasoning": {"type": "string"},
                    "pio_verification_required": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "risk_flags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "recommended_response_path": {
                        "type": "string",
                    },
                },
            },
        },
        "mandatory_response_elements": {
            "type": "array",
            "items": {"type": "string"},
        },
        "human_review_required": {
            "type": "boolean",
        },
    },
}


class PIOPipelineError(RuntimeError):
    """Raised when a PIO advisory analysis cannot be completed safely."""


def _find_rti_act_path() -> Path:
    """Locate the RTI Act reference file without depending on the run directory."""
    configured_path = os.getenv("RTI_ACT_JSON_PATH", "").strip()

    candidates = []
    if configured_path:
        candidates.append(Path(configured_path).expanduser())

    candidates.extend(
        [
            PROJECT_ROOT / ACT_FILENAME,
            WEBUI_DIR / ACT_FILENAME,
            Path.cwd() / ACT_FILENAME,
        ]
    )

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    attempted = ", ".join(str(item) for item in candidates)
    raise PIOPipelineError(
        f"RTI Act JSON file was not found. Checked: {attempted}"
    )


def _load_rti_act() -> tuple[dict[str, Any], Path]:
    act_path = _find_rti_act_path()

    try:
        parsed = json.loads(act_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as error:
        raise PIOPipelineError(
            f"RTI Act JSON file is not UTF-8 readable: {act_path}"
        ) from error
    except json.JSONDecodeError as error:
        raise PIOPipelineError(
            f"RTI Act JSON file contains invalid JSON: {act_path}"
        ) from error

    if not isinstance(parsed, dict) or not isinstance(parsed.get("sections"), list):
        raise PIOPipelineError(
            "RTI Act JSON must contain a top-level 'sections' list."
        )

    return parsed, act_path


def _json_for_prompt(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _parse_json_object(raw_text: str, stage_name: str) -> dict[str, Any]:
    """Parse a model response, tolerating accidental Markdown JSON fences."""
    text = str(raw_text or "").strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise PIOPipelineError(
            f"{stage_name} returned invalid JSON."
        ) from error

    if not isinstance(data, dict):
        raise PIOPipelineError(
            f"{stage_name} must return a JSON object at the top level."
        )

    return data


def _require_keys(
    data: dict[str, Any],
    keys: tuple[str, ...],
    stage_name: str,
) -> None:
    missing = [key for key in keys if key not in data]
    if missing:
        raise PIOPipelineError(
            f"{stage_name} is missing required fields: {', '.join(missing)}."
        )


def _validate_extraction(data: dict[str, Any]) -> None:
    _require_keys(
        data,
        (
            "case_type",
            "language",
            "public_authority",
            "applicant_name",
            "application_reference",
            "submission_date",
            "period",
            "information_points",
            "extraction_uncertainties",
        ),
        "RTI extraction",
    )

    if data.get("case_type") != "rti_application":
        raise PIOPipelineError(
            "RTI extraction must use case_type='rti_application'."
        )

    if not isinstance(data.get("period"), dict):
        raise PIOPipelineError("RTI extraction field 'period' must be an object.")

    if not isinstance(data.get("information_points"), list):
        raise PIOPipelineError(
            "RTI extraction field 'information_points' must be a list."
        )

    if not isinstance(data.get("extraction_uncertainties"), list):
        raise PIOPipelineError(
            "RTI extraction field 'extraction_uncertainties' must be a list."
        )

    for index, point in enumerate(data["information_points"], start=1):
        if not isinstance(point, dict):
            raise PIOPipelineError(
                f"RTI extraction information point {index} must be an object."
            )
        _require_keys(
            point,
            ("point_no", "requested_information", "record_types_requested"),
            f"RTI extraction information point {index}",
        )
        if not isinstance(point.get("record_types_requested"), list):
            raise PIOPipelineError(
                f"RTI extraction information point {index} "
                "field 'record_types_requested' must be a list."
            )


def _valid_act_provisions(act_data: dict[str, Any]) -> set[str]:
    valid: set[str] = set()

    for section in act_data.get("sections", []):
        if not isinstance(section, dict):
            continue

        section_number = str(section.get("section_number", "")).strip()
        if section_number:
            valid.add(section_number)

        for subsection in section.get("subsections", []):
            if not isinstance(subsection, dict):
                continue
            subsection_id = str(subsection.get("subsection_id", "")).strip()
            if subsection_id:
                valid.add(subsection_id)

    if not valid:
        raise PIOPipelineError(
            "RTI Act JSON contains no valid sections or subsections."
        )

    return valid


def _normalise_provision(value: Any) -> str:
    """Accept 'Section 8(1)(j)', 'धारा 8(1)(j)', or '8(1)(j)'."""
    text = str(value or "").strip()
    text = re.sub(r"^(?:section|sec\.?|धारा)\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", "", text)
    return text


def _coerce_valid_provisions(
    values: Any,
    valid_provisions: set[str],
) -> list[str]:
    if not isinstance(values, list):
        return []

    cleaned: list[str] = []

    def add_if_valid(candidate: Any) -> None:
        normalized = _normalise_provision(candidate)
        if normalized in valid_provisions and normalized not in cleaned:
            cleaned.append(normalized)

    for value in values:
        add_if_valid(value)

        for candidate in re.findall(r"\d+(?:\([0-9A-Za-z]+\))*", str(value or "")):
            add_if_valid(candidate)

    return cleaned


def _validate_provision_list(
    values: Any,
    valid_provisions: set[str],
    field_label: str,
) -> None:
    if not isinstance(values, list):
        raise PIOPipelineError(f"{field_label} must be a list.")

    original = list(values)
    cleaned = _coerce_valid_provisions(values, valid_provisions)

    if cleaned != original:
        print(
            f"[PIO] Sanitized {field_label}: "
            f"{original!r} -> {cleaned!r}"
        )

    values[:] = cleaned


def _validate_legal_analysis(
    data: dict[str, Any],
    valid_provisions: set[str],
) -> None:
    _require_keys(
        data,
        (
            "case_level_checks",
            "point_analysis",
            "mandatory_response_elements",
            "human_review_required",
        ),
        "Legal analysis",
    )

    if not isinstance(data.get("case_level_checks"), list):
        raise PIOPipelineError("Legal analysis 'case_level_checks' must be a list.")
    if not isinstance(data.get("point_analysis"), list):
        raise PIOPipelineError("Legal analysis 'point_analysis' must be a list.")
    if not isinstance(data.get("mandatory_response_elements"), list):
        raise PIOPipelineError(
            "Legal analysis 'mandatory_response_elements' must be a list."
        )
    if not isinstance(data.get("human_review_required"), bool):
        raise PIOPipelineError(
            "Legal analysis 'human_review_required' must be true or false."
        )

    for index, item in enumerate(data["case_level_checks"], start=1):
        if not isinstance(item, dict):
            raise PIOPipelineError(
                f"Legal analysis case-level check {index} must be an object."
            )
        _require_keys(
            item,
            ("check", "status", "legal_basis"),
            f"Legal analysis case-level check {index}",
        )
        _validate_provision_list(
            item["legal_basis"],
            valid_provisions,
            f"Legal analysis case-level check {index} legal_basis",
        )

    for index, item in enumerate(data["point_analysis"], start=1):
        if not isinstance(item, dict):
            raise PIOPipelineError(
                f"Legal analysis point {index} must be an object."
            )
        _require_keys(
            item,
            (
                "point_no",
                "request_type",
                "record_status",
                "possible_action",
                "applicable_provisions",
                "legal_reasoning",
                "pio_verification_required",
                "risk_flags",
                "recommended_response_path",
            ),
            f"Legal analysis point {index}",
        )
        _validate_provision_list(
            item["applicable_provisions"],
            valid_provisions,
            f"Legal analysis point {index} applicable_provisions",
        )

        for list_field in ("pio_verification_required", "risk_flags"):
            if not isinstance(item.get(list_field), list):
                raise PIOPipelineError(
                    f"Legal analysis point {index} field '{list_field}' must be a list."
                )


def _build_extraction_prompt(rti_text: str) -> str:
    return f"""
You are a strict RTI application extraction system for a Public Information Officer.

Extract facts only from the RTI application. Do not perform legal reasoning.

Mandatory rules:
1. Return a single valid JSON object only. Do not use Markdown fences.
2. Do not invent names, departments, dates, document names, identifiers, or records.
3. Use null for a scalar value that is absent or uncertain.
4. Keep each distinct request in a separate information_points item.
5. Preserve the RTI application's language where practical.
6. If a request is vague, record the uncertainty instead of guessing.

Return exactly this object shape:
{{
  "case_type": "rti_application",
  "language": null,
  "public_authority": null,
  "applicant_name": null,
  "application_reference": null,
  "submission_date": null,
  "period": {{
    "from": null,
    "to": null
  }},
  "information_points": [
    {{
      "point_no": 1,
      "requested_information": "",
      "record_types_requested": [],
      "source_span": null
    }}
  ],
  "extraction_uncertainties": []
}}

<rti_application>
{rti_text}
</rti_application>
""".strip()


def _build_analysis_prompt(
    rti_extraction: dict[str, Any],
    full_rti_act_json: str,
) -> str:
    return f"""
You are an RTI Act legal-analysis assistant for a Public Information Officer.

Analyse the incoming RTI application point by point using ONLY the RTI Act
reference JSON included below. The legal packet is the source of truth.

Mandatory rules:
1. Return a single valid JSON object only. Do not use Markdown fences.
2. Do not invent a legal section, subsection, fact, record, date, authority,
   document, or exemption.
3. Do not make a final disclosure or denial decision.
4. Use VERIFY whenever confirmation from the department is required.
5. For any possible Section 8 exemption, evaluate Section 8(2) and Section 10
   where those provisions are present in the supplied legal packet.
6. Cite provisions only as exact identifiers present in the legal packet, such as
   "2(f)", "7(1)", "8(2)", or "10". Do not prefix them with "Section" or "धारा".
7. Produce a separate point_analysis object for every incoming information point.
8. Section 4(1)(a) only concerns cataloguing, indexing, and maintenance
   of records that exist. Do not use it to assume that a requested record
   was created, retained, or is currently available.

9. Do not use Section 2(h) unless qualification of the body as a public
   authority is actually a live issue in the RTI application.

10. mandatory_response_elements must contain at least:
   - applicable response timeline under 7(1);
   - transfer check under 6(3), if another public authority may hold records;
   - conditional requirement under 7(8), only if information is withheld.
Return exactly this object shape:
{{
  "case_level_checks": [
    {{
      "check": "",
      "status": "VERIFY",
      "legal_basis": []
    }}
  ],
  "point_analysis": [
    {{
      "point_no": 1,
      "request_type": "",
      "record_status": "VERIFY",
      "possible_action": "",
      "applicable_provisions": [],
      "legal_reasoning": "",
      "pio_verification_required": [],
      "risk_flags": [],
      "recommended_response_path": ""
    }}
  ],
  "mandatory_response_elements": [],
  "human_review_required": true
}}
STRICT BACKEND VALIDATION RULES:

Your response will be rejected unless ALL four top-level keys exist:

1. "case_level_checks"
2. "point_analysis"
3. "mandatory_response_elements"
4. "human_review_required"

Never return only "case_level_checks".

For every item in incoming_rti_json.information_points, create exactly one
corresponding object inside "point_analysis".

For this RTI, if there is one information point, then "point_analysis"
must contain one object.

Even if information is uncertain:
- use "VERIFY"
- use empty arrays where necessary
- but never omit mandatory keys.

Before finalizing your response, verify that:
- all four top-level keys are present;
- point_analysis is not empty when information_points is not empty;
- every point_analysis object includes every required field.


<incoming_rti_json>
{_json_for_prompt(rti_extraction)}
</incoming_rti_json>

<full_rti_act_reference_json>
{full_rti_act_json}
</full_rti_act_reference_json>
""".strip()

def _collect_cited_provisions(
    legal_analysis: dict[str, Any],
    valid_provisions: set[str],
) -> list[str]:
    """Collect only RTI Act provisions already validated in Call 2."""
    cited: set[str] = set()

    def add_candidate(value: Any) -> None:
        text = str(value or "").strip()
        if not text:
            return

        normalized = _normalise_provision(text)
        if normalized in valid_provisions:
            cited.add(normalized)

        # Supports examples such as 2(f), 6(3), 8(1)(d), 10(1).
        for candidate in re.findall(r"\d+(?:\([0-9A-Za-z]+\))*", text):
            normalized_candidate = _normalise_provision(candidate)
            if normalized_candidate in valid_provisions:
                cited.add(normalized_candidate)

    for check in legal_analysis.get("case_level_checks", []):
        if isinstance(check, dict):
            for provision in check.get("legal_basis", []):
                add_candidate(provision)

    for point in legal_analysis.get("point_analysis", []):
        if isinstance(point, dict):
            for provision in point.get("applicable_provisions", []):
                add_candidate(provision)

    for element in legal_analysis.get("mandatory_response_elements", []):
        add_candidate(element)

    if not cited:
        fallback = [
            provision
            for provision in ("2(f)", "6", "7", "8", "10", "19")
            if provision in valid_provisions
        ]
        print(
            "[PIO] No validated provisions cited by Call 2; "
            f"using fallback RTI Act packet: {fallback!r}"
        )
        return fallback

    return sorted(cited)


def _build_cited_act_packet(
    act_data: dict[str, Any],
    legal_analysis: dict[str, Any],
    valid_provisions: set[str],
) -> dict[str, Any]:
    """
    Build a compact legal packet for Call 3.

    This is deterministic Python selection, not LLM retrieval.
    """
    cited_ids = _collect_cited_provisions(
        legal_analysis=legal_analysis,
        valid_provisions=valid_provisions,
    )

    cited_set = set(cited_ids)
    selected_sections: list[dict[str, Any]] = []
    found_ids: set[str] = set()

    for section in act_data.get("sections", []):
        if not isinstance(section, dict):
            continue

        section_id = str(section.get("section_number", "")).strip()
        raw_subsections = section.get("subsections", [])
        if not isinstance(raw_subsections, list):
            raw_subsections = []

        section_is_cited = section_id in cited_set

        if section_is_cited:
            selected_subsections = [
                subsection
                for subsection in raw_subsections
                if isinstance(subsection, dict)
            ]
        else:
            selected_subsections = [
                subsection
                for subsection in raw_subsections
                if isinstance(subsection, dict)
                and str(subsection.get("subsection_id", "")).strip() in cited_set
            ]

        if not section_is_cited and not selected_subsections:
            continue

        compact_subsections = []
        for subsection in selected_subsections:
            subsection_id = str(subsection.get("subsection_id", "")).strip()
            if subsection_id:
                found_ids.add(subsection_id)

            compact_subsections.append(
                {
                    "subsection_id": subsection_id,
                    "title_en": subsection.get("title_en"),
                    "title_hi": subsection.get("title_hi"),
                    "definition_en": subsection.get("definition_en"),
                    "definition_hi": subsection.get("definition_hi"),
                }
            )

        if section_is_cited:
            found_ids.add(section_id)

        selected_sections.append(
            {
                "section_number": section_id,
                "title_en": section.get("title_en"),
                "title_hi": section.get("title_hi"),
                "summary_en": section.get("summary_en"),
                "summary_hi": section.get("summary_hi"),
                "pio_response_note": section.get("pio_response_note"),
                "source_reference": section.get("source_reference"),
                "selected_subsections": compact_subsections,
            }
        )

    missing = cited_set - found_ids
    if missing:
        raise PIOPipelineError(
            "Could not build Call 3 legal packet for validated provision(s): "
            + ", ".join(sorted(missing))
        )

    return {
        "source": "Right to Information Act, 2005",
        "selected_provision_ids": cited_ids,
        "sections": selected_sections,
    }
def _build_response_prompt(
    rti_extraction: dict[str, Any],
    legal_analysis: dict[str, Any],
    cited_act_packet: dict[str, Any],
) -> str:
    return f"""
You are an RTI advisory assistant for a Public Information Officer.

Create a readable, rigorous, point-wise PIO advisory report from validated
inputs. This is decision support only, not a final official order.

OUTPUT CONTRACT:
1. Return Markdown prose only.
2. Begin exactly with: ## PIO Advisory Report
3. Do not return JSON, JSON arrays, code fences, XML tags, or raw input data.
4. Do not repeat the extraction JSON or legal-analysis JSON.
5. Use the RTI application's language where practical.

LEGAL SAFETY RULES:
1. Use only facts from RTI extraction, validated legal analysis, and the cited
   RTI Act packet below.
2. Do not claim that any record exists, is unavailable, or is held by an
   authority unless that fact is verified.
3. Mark unresolved matters as "PIO verification required".
4. Do not make a final disclosure or denial decision.
5. Use only citations already present in validated legal analysis.
6. For partial exemption, mention severability/redaction only where validated
   legal analysis supports it.
7. Do not add CIC or CG SIC precedents at this stage.

Use this structure:

## PIO Advisory Report

### RTI Application Summary

### Point-wise Analysis
For each point include:
- Requested information
- PIO verification required
- Relevant Act provisions
- Suggested response path
- Risk flags

### Mandatory Procedural Checks

### Human Verification Required

<rti_extraction>
{_json_for_prompt(rti_extraction)}
</rti_extraction>

<validated_legal_analysis>
{_json_for_prompt(legal_analysis)}
</validated_legal_analysis>

<cited_rti_act_packet>
{_json_for_prompt(cited_act_packet)}
</cited_rti_act_packet>
""".strip()

def _generate_json_with_one_retry(
    stage_name: str,
    prompt: str,
    validate: Callable[[dict[str, Any]], None],
    max_tokens: int,
    reasoning_effort: str,
    json_schema: dict[str, Any],
    json_schema_name: str,
) -> dict[str, Any]:
    """Generate and validate JSON, with one correction retry for malformed output."""
    last_error: Exception | None = None

    for attempt in range(2):
        correction = ""
        if attempt == 1:
            correction = f"""

Your previous output failed backend validation:
{last_error}

Correct the issue. Return the complete JSON object only; do not add explanation.
"""

        try:
            generated = generate_text(
                prompt=f"{prompt}{correction}",
                temperature=0.0,
                max_tokens=max_tokens,
                timeout_seconds=int(os.getenv("PIO_LLM_TIMEOUT_SECONDS", "240")),
                json_mode=True,
                reasoning_effort=reasoning_effort,
                json_schema=json_schema,
                json_schema_name=json_schema_name,
            )
            parsed = _parse_json_object(generated, stage_name)
            validate(parsed)
            return parsed
        except (PIOPipelineError, LLMProviderError) as error:
            last_error = error

    raise PIOPipelineError(
        f"{stage_name} failed validation after one correction retry: {last_error}"
    )

def _validate_advisory_report(report: str) -> str:
    text = _normalise_advisory_report(report)

    if not text:
        raise PIOPipelineError(
            "PIO advisory response generation returned an empty report."
        )

    if text.startswith(("{", "[")):
        try:
            json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            raise PIOPipelineError(
                "PIO advisory response returned JSON instead of a readable report."
            )

    if not text.startswith(ADVISORY_REPORT_HEADING):
        raise PIOPipelineError(
            "PIO advisory response must begin with '## PIO Advisory Report'."
        )

    if len(text) < 220:
        raise PIOPipelineError(
            "PIO advisory response is too short to be a usable report."
        )

    return text


def _normalise_advisory_report(report: str) -> str:
    text = str(report or "").strip().lstrip(chr(65279)).strip()

    fenced = re.match(
        r"^```(?:markdown|md|text)?\s*\n(?P<body>.*?)\n```\s*$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced:
        text = fenced.group("body").strip()

    heading_index = text.find(ADVISORY_REPORT_HEADING)
    if heading_index > 0:
        text = text[heading_index:].strip()

    if text.startswith(ADVISORY_REPORT_HEADING):
        return text

    lines = text.splitlines()
    first_line = lines[0].strip() if lines else ""
    rest = "\n".join(lines[1:]).strip()
    normalized_heading = re.sub(r"^[#\s:.-]+", "", first_line).strip().casefold()
    normalized_heading = re.sub(r"\s+", " ", normalized_heading)

    if normalized_heading in {
        "pio advisory report",
        "public information officer advisory report",
    }:
        return (
            ADVISORY_REPORT_HEADING
            if not rest
            else f"{ADVISORY_REPORT_HEADING}\n\n{rest}"
        )

    if text and not text.startswith(("{", "[")):
        return f"{ADVISORY_REPORT_HEADING}\n\n{text}"

    return text


def _generate_advisory_report_with_one_retry(
    response_prompt: str,
) -> str:
    last_error: Exception | None = None
    max_tokens = int(os.getenv("PIO_RESPONSE_MAX_TOKENS", "4000"))
    timeout_seconds = int(os.getenv("PIO_LLM_TIMEOUT_SECONDS", "240"))

    for attempt in range(2):
        correction = ""
        attempt_max_tokens = max_tokens if attempt == 0 else min(max_tokens, 2200)

        if attempt == 1:
            correction = f"""

Your previous output failed report validation:
{last_error}

Return only a readable Markdown PIO advisory report.
Do not return JSON.
Begin exactly with:
## PIO Advisory Report
"""

        try:
            generated = generate_text(
                prompt=f"{response_prompt}{correction}",
                temperature=0.1,
                max_tokens=attempt_max_tokens,
                timeout_seconds=timeout_seconds,
                json_mode=False,
                reasoning_effort="medium",
            )

            if os.getenv("PIO_DEBUG_REPORT_OUTPUT", "0") == "1":
                print(
                    f"\n[PIO][Call 3][Attempt {attempt + 1}] "
                    f"output length: {len(generated)}"
                )
                print("[PIO][Call 3] Raw output preview:")
                print(repr(generated[:3000]))
                print()

            return _validate_advisory_report(generated)
        
        
        except PIOPipelineError as error:
            last_error = error

        except LLMProviderError as error:
            raise PIOPipelineError(
                f"Sarvam Call 3 (PIO advisory report) failed: {error}"
            ) from error

    raise PIOPipelineError(
        f"Sarvam Call 3 returned an invalid advisory report after one retry: "
        f"{last_error}"
    )

def _ensure_precedent_prompt(report: str) -> str:
    normalized = str(report or "").strip()
    if not normalized:
        raise PIOPipelineError("PIO advisory response generation returned an empty report.")

    if PRECEDENT_PROMPT.casefold() not in normalized.casefold():
        normalized = f"{normalized}\n\n{PRECEDENT_PROMPT}"

    return normalized


def analyze_pio_application(rti_text: str) -> dict[str, Any]:
    """
    Run the three-call PIO advisory workflow.

    Call 1: RTI text -> structured extraction JSON
    Call 2: Extraction JSON + complete RTI Act JSON -> legal analysis JSON
    Call 3: Extraction JSON + validated analysis + Act JSON -> readable advisory
    """
    rti_text = str(rti_text or "").strip()
    if not rti_text:
        raise PIOPipelineError("RTI application text cannot be empty.")

    max_rti_chars = int(os.getenv("PIO_MAX_RTI_CHARS", "50000"))
    if len(rti_text) > max_rti_chars:
        raise PIOPipelineError(
            f"RTI application text exceeds the configured limit of {max_rti_chars} characters."
        )

    rti_act_data, act_path = _load_rti_act()
    valid_provisions = _valid_act_provisions(rti_act_data)
    full_rti_act_json = _json_for_prompt(rti_act_data)

    rti_extraction = _generate_json_with_one_retry(
        stage_name="Sarvam Call 1 (RTI extraction)",
        prompt=_build_extraction_prompt(rti_text),
        validate=_validate_extraction,
        max_tokens=int(os.getenv("PIO_EXTRACTION_MAX_TOKENS", "3000")),
        reasoning_effort="low",
        json_schema=RTI_EXTRACTION_SCHEMA,
        json_schema_name="rti_extraction",
    )

    legal_analysis = _generate_json_with_one_retry(
            stage_name="Sarvam Call 2 (legal analysis)",
            prompt=_build_analysis_prompt(rti_extraction, full_rti_act_json),
            validate=lambda data: _validate_legal_analysis(data, valid_provisions),
            max_tokens=int(os.getenv("PIO_ANALYSIS_MAX_TOKENS", "3800")),
            reasoning_effort="medium",
            json_schema=LEGAL_ANALYSIS_SCHEMA,
            json_schema_name="rti_legal_analysis",
        )

    cited_act_packet = _build_cited_act_packet(
        act_data=rti_act_data,
        legal_analysis=legal_analysis,
        valid_provisions=valid_provisions,
    )

    response_prompt = _build_response_prompt(
        rti_extraction=rti_extraction,
        legal_analysis=legal_analysis,
        cited_act_packet=cited_act_packet,
    )

    generated_report = _generate_advisory_report_with_one_retry(
        response_prompt=response_prompt,
    )

    final_report = _ensure_precedent_prompt(generated_report)
    
    return {
        "rti_extraction": rti_extraction,
        "legal_analysis": legal_analysis,
        "pio_advisory_report": final_report,
        "validation": {
            "extraction_json_valid": True,
            "analysis_json_valid": True,
            "legal_citations_valid": True,
            "report_text_valid": True,
            "call_3_used_cited_act_packet": True,
            "call_3_cited_provisions": cited_act_packet["selected_provision_ids"],
            "valid_provision_count": len(valid_provisions),
            "rti_act_json_path": str(act_path),
        },
    }
