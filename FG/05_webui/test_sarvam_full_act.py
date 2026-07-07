import json

from services.llm_provider import generate_text
from services.pio_pipeline import (
    _load_rti_act,
    _build_analysis_prompt,
    _valid_act_provisions,
    _validate_legal_analysis,
    LEGAL_ANALYSIS_SCHEMA,
)
act_data, act_path = _load_rti_act()

sample_extraction = {
    "case_type": "rti_application",
    "language": "hi",
    "public_authority": None,
    "applicant_name": None,
    "application_reference": None,
    "submission_date": None,
    "period": {
        "from": "2024-04",
        "to": "2025-03",
    },
    "information_points": [
        {
            "point_no": 1,
            "requested_information": "Payment and penalty related records.",
            "record_types_requested": [
                "payment records",
                "penalty records",
            ],
            "source_span": None,
        }
    ],
    "extraction_uncertainties": [],
}

full_act_json = json.dumps(
    act_data,
    ensure_ascii=False,
    indent=2,
)

prompt = _build_analysis_prompt(
    sample_extraction,
    full_act_json,
)

print("RTI Act file:", act_path)
print("Prompt characters:", len(prompt))
print("Prompt UTF-8 bytes:", len(prompt.encode("utf-8")))
print("\nCalling Sarvam...\n")

response = generate_text(
    prompt=prompt,
    temperature=0.0,
    max_tokens=3800,
    timeout_seconds=240,
    json_mode=True,
    reasoning_effort="medium",
    json_schema=LEGAL_ANALYSIS_SCHEMA,
)

analysis = json.loads(response)

_validate_legal_analysis(
    analysis,
    _valid_act_provisions(act_data),
)

print("VALID LEGAL ANALYSIS JSON")
print(json.dumps(analysis, ensure_ascii=False, indent=2))

print(response)