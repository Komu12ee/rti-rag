import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "rag_pipeline_parallel_test",
    ROOT / "rag_pipeline.py",
)
RAG = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = RAG
SPEC.loader.exec_module(RAG)


def point(collection, point_id, priority=0):
    return SimpleNamespace(
        id=point_id,
        payload={
            "_retrieval_collection": collection,
            "retrieval_priority": priority,
            "sparse_embedding": {},
        },
    )


def test_same_numeric_id_remains_distinct_across_collections():
    db3_point = point("db3", 0)
    cgsic_point = point("cgsic_important_decisions_v1", 0)

    assert RAG.point_identity(db3_point) != RAG.point_identity(cgsic_point)


def test_legal_priority_uses_collection_safe_identity():
    db3_point = point("db3", 7, priority=0)
    cgsic_point = point("cgsic_important_decisions_v1", 7, priority=100)
    scores = [
        (RAG.point_identity(db3_point), 0.5),
        (RAG.point_identity(cgsic_point), 0.5),
    ]

    boosted = RAG.apply_legal_priority(scores, [db3_point, cgsic_point])

    assert boosted[0][0] == RAG.point_identity(cgsic_point)
    assert boosted[0][1] > boosted[1][1]


def test_cgsic_actual_pdf_is_used_from_payload():
    payload = {
        "source": "Imp_Dicisions_CGSIC.pdf",
        "actual_pdf": "CGSIC_IMPORTANT_134.pdf",
    }

    assert RAG.get_payload_actual_filename(payload) == "CGSIC_IMPORTANT_134.pdf"
