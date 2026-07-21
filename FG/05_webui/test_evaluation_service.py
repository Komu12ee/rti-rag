import json

import pytest

from services import evaluation_service as evaluation
from services import llm_provider


def test_parse_csv_benchmark_normalises_ground_truth_fields():
    content = (
        "question,expected_answer,relevant_documents,expected_citations,expected_route\n"
        '"Who is the PIO?","Example Officer","pio-directory|office-42",'
        '"pio-directory","POSTGRES"\n'
    ).encode("utf-8")

    cases = evaluation.parse_benchmark_file("benchmark.csv", content)

    assert cases == [
        {
            "question": "Who is the PIO?",
            "expected_answer": "Example Officer",
            "relevant_documents": ["pio-directory", "office-42"],
            "expected_citations": ["pio-directory"],
            "metadata": {"expected_route": "POSTGRES"},
        }
    ]


def test_parse_json_benchmark_accepts_cases_envelope():
    content = json.dumps(
        {
            "cases": [
                {
                    "query": "What is Section 7?",
                    "ground_truth": "A response is generally due within 30 days.",
                    "documents": ["rti-act.pdf"],
                }
            ]
        }
    ).encode("utf-8")

    cases = evaluation.parse_benchmark_file("benchmark.json", content)

    assert cases[0]["question"] == "What is Section 7?"
    assert cases[0]["expected_answer"].startswith("A response")
    assert cases[0]["relevant_documents"] == ["rti-act.pdf"]


def test_retrieval_metrics_score_ranked_expected_documents():
    metrics = evaluation.retrieval_metrics(
        ["document-a", "document-b"],
        [
            {"source": "unrelated"},
            {"source": "document-b"},
            {"source": "document-a"},
        ],
        3,
    )

    assert metrics["precision_at_3"] == pytest.approx(2 / 3, abs=1e-6)
    assert metrics["recall_at_3"] == 1.0
    assert metrics["mrr"] == 0.5
    assert 0.6 < metrics["ndcg"] < 0.7


def test_pipeline_evaluation_tracks_quality_route_usage_and_cost(monkeypatch):
    monkeypatch.setenv("SARVAM_INPUT_COST_PER_1M_INR", "4")
    monkeypatch.setenv("SARVAM_CACHED_INPUT_COST_PER_1M_INR", "2.5")
    monkeypatch.setenv("SARVAM_OUTPUT_COST_PER_1M_INR", "16")
    case = {
        "question": "Who is the PIO?",
        "expected_answer": "Example Officer is the PIO.",
        "relevant_documents": ["pio-directory"],
        "expected_citations": ["pio-directory"],
        "metadata": {"expected_route": "POSTGRES"},
    }
    output = {
        "answer": "Example Officer is the PIO.",
        "route": "POSTGRES",
        "retrieved_documents": [
            {
                "source": "pio-directory",
                "text": "Example Officer is the PIO.",
            }
        ],
        "actual_citations": ["pio-directory"],
        "latency_ms": 125,
        "usage_records": [
            {
                "provider": "sarvam",
                "model": "sarvam-105b",
                "prompt_tokens": 100,
                "cached_prompt_tokens": 20,
                "completion_tokens": 25,
                "total_tokens": 125,
            }
        ],
    }

    result = evaluation.evaluate_pipeline_output(
        case,
        output,
        {"top_k": 5, "judge_enabled": False},
    )

    assert result["metrics"]["recall_at_5"] == 1.0
    assert result["metrics"]["faithfulness"] == 1.0
    assert result["metrics"]["route_correctness"] == 1.0
    assert result["failure_cluster"] == "passed"
    assert result["token_usage"]["total"]["total_tokens"] == 125
    assert result["estimated_cost_inr"] > 0


def test_pipeline_evaluation_clusters_routing_before_retrieval_failure():
    result = evaluation.evaluate_pipeline_output(
        {
            "question": "Find the PIO",
            "expected_answer": "Example Officer",
            "relevant_documents": ["pio-directory"],
            "expected_citations": ["pio-directory"],
            "metadata": {"expected_route": "POSTGRES"},
        },
        {
            "answer": "Unknown",
            "route": "QDRANT",
            "retrieved_documents": [],
            "latency_ms": 10,
            "usage_records": [],
        },
        {"top_k": 3, "judge_enabled": False},
    )

    assert result["metrics"]["route_correctness"] == 0.0
    assert result["metrics"]["recall_at_3"] == 0.0
    assert result["failure_cluster"] == "routing_failure"
    assert "retrieval_miss" in result["failure_tags"]


def test_experiment_config_parses_boolean_strings_and_prompt_variant():
    config = evaluation.normalise_experiment_config(
        {
            "reranker_enabled": "false",
            "use_kg": "0",
            "use_multi_query": "yes",
            "judge_enabled": "off",
            "prompt_instruction": "Answer in one short paragraph.",
        }
    )

    assert config["reranker_enabled"] is False
    assert config["use_kg"] is False
    assert config["use_multi_query"] is True
    assert config["judge_enabled"] is False
    assert config["prompt_instruction"] == "Answer in one short paragraph."


def test_generate_text_forwards_per_experiment_model_override(monkeypatch):
    captured = {}

    def fake_sarvam(**kwargs):
        captured.update(kwargs)
        return "answer"

    monkeypatch.setattr(llm_provider, "get_llm_mode", lambda: "sarvam")
    monkeypatch.setattr(llm_provider, "_generate_with_sarvam", fake_sarvam)

    answer = llm_provider.generate_text(
        "question",
        model_override="sarvam-experiment-model",
    )

    assert answer == "answer"
    assert captured["model_override"] == "sarvam-experiment-model"
