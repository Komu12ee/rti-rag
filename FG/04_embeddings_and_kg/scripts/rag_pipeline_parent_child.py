"""
Parent-child RAG retrieval pipeline for CHiPPY.

Retrieval flow:
1) Search child chunks in Qdrant (dense + optional sparse hybrid)
2) Map top children to unique parents
3) Load parent chunk text from files
4) Rerank parent chunks
5) Return final context for LLM answer generation
"""

from __future__ import annotations

import os
import sys
import atexit
from pathlib import Path
from typing import Any

import requests
from FlagEmbedding import BGEM3FlagModel, FlagReranker
from qdrant_client import QdrantClient

for stream_name in ("stdout", "stderr"):
    stream = getattr(sys, stream_name, None)
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def _paths() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    
    # Determine Qdrant mode (remote Docker service or local embedded)
    qdrant_mode = os.getenv("QDRANT_MODE", "local").lower()
    
    return {
        "root": root,
        "chunk_dir": Path(os.getenv("CHIPPY_CHUNK_DIR", str(root / "03_chunking" / "output"))),
        "parent_dir": Path(os.getenv("CHIPPY_PARENT_DIR", str(root / "03_chunking" / "output"))),
        "files_mapping": Path(os.getenv("CHIPPY_FILES_MAPPING", str(root.parent / "files.txt"))),
        "collection": os.getenv("CHIPPY_QDRANT_COLLECTION", "db3"),
        
        # Local Qdrant mode (embedded, development)
        "qdrant_mode": qdrant_mode,
        "qdrant_local_path": Path(
            os.getenv(
                "CHIPPY_QDRANT_LOCAL_PATH",
                str(root / "04_embeddings_and_kg" / "db" / "qdrant_local")
            )
        ),
        
        # Remote Qdrant mode (Docker service, production)
        "qdrant_host": os.getenv("QDRANT_HOST", "localhost"),
        "qdrant_port": int(os.getenv("QDRANT_PORT", "6333")),
        "qdrant_api_key": os.getenv("QDRANT_API_KEY", None),
        "qdrant_timeout": int(os.getenv("QDRANT_TIMEOUT", "60")),
        
        # Ollama configuration
        "ollama_host": os.getenv("OLLAMA_HOST", os.getenv("CHIPPY_OLLAMA_HOST", "localhost")),
        "ollama_port": int(os.getenv("OLLAMA_PORT", os.getenv("CHIPPY_OLLAMA_PORT", "11434"))),
        "ollama_model": os.getenv("OLLAMA_MODEL", os.getenv("CHIPPY_OLLAMA_MODEL", "qwen2.5:3b")),
        "embedding_model": os.getenv("EMBEDDING_MODEL", str(root / "models" / "bge-m3")),
        "reranker_model": os.getenv("RERANKER_MODEL", str(root / "models" / "bge-reranker-v2-m3")),
    }


CFG = _paths()

HYBRID_ALPHA = 0.6
RERANK_MIN_K = 2
RERANK_MAX_K = 4
RERANK_THRESHOLD = 0.60
MAX_LENGTH = 1024


print(f"[RAG] Loading embedding model: {CFG['embedding_model']}")
model = BGEM3FlagModel(CFG["embedding_model"], use_fp16=True)
model.return_sparse = True
print(f"[RAG] Loading reranker model: {CFG['reranker_model']}")
reranker = FlagReranker(CFG["reranker_model"], use_fp16=True)

# ── Connect to Qdrant ────────────────────────────────────────
# Support both local embedded (development) and remote service (Docker)
qdrant_mode = CFG["qdrant_mode"]

if qdrant_mode == "remote":
    # Connect to remote Qdrant service (Docker, production)
    print(f"[RAG] Connecting to remote Qdrant at {CFG['qdrant_host']}:{CFG['qdrant_port']}...")
    try:
        client = QdrantClient(
            host=CFG['qdrant_host'],
            port=CFG['qdrant_port'],
            api_key=CFG['qdrant_api_key'],
            timeout=CFG['qdrant_timeout']
        )
        client.get_collections()
        print(f"[RAG] ✓ Connected to remote Qdrant at {CFG['qdrant_host']}:{CFG['qdrant_port']}")
    except Exception as e:
        print(f"[RAG] ✗ Failed to connect to remote Qdrant: {e}")
        print(f"[RAG] Make sure Qdrant service is running at {CFG['qdrant_host']}:{CFG['qdrant_port']}")
        exit(1)
else:
    # Use local embedded Qdrant (default for local development)
    print(f"[RAG] Connecting to local embedded Qdrant at {CFG['qdrant_local_path']}...")
    try:
        CFG["qdrant_local_path"].mkdir(parents=True, exist_ok=True)
        client = QdrantClient(path=str(CFG["qdrant_local_path"]))
        client.get_collections()
        print("[RAG] ✓ Connected to local embedded Qdrant")
    except Exception as e:
        print(f"[RAG] ✗ Failed to initialize local Qdrant: {e}")
        print(f"[RAG] Make sure {CFG['qdrant_local_path']} is writable")
        exit(1)


def _cleanup_qdrant():
    """Explicitly close Qdrant client on exit to avoid shutdown import errors."""
    try:
        if 'client' in globals():
            client.close()
    except Exception:
        pass  # Suppress cleanup errors during shutdown


atexit.register(_cleanup_qdrant)


def load_file_mapping(mapping_file: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    try:
        with open(mapping_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or "-------->" not in line:
                    continue
                actual_name, output_name = line.split("-------->")
                mapping[output_name.strip().replace(".pdf", "")] = actual_name.strip()
    except Exception as e:
        print(f"[RAG] Warning: could not load file mapping from {mapping_file}: {e}")
    return mapping


FILE_MAPPING = load_file_mapping(CFG["files_mapping"])


def initialize_pipeline() -> dict[str, bool | str]:
    """Initialize and verify the RAG pipeline components."""
    status = {
        "initialized": False,
        "qdrant_connected": False,
        "collection_exists": False,
        "embeddings_loaded": False,
        "error": None,
    }

    try:
        # Verify Qdrant connection
        client.get_collections()
        status["qdrant_connected"] = True
        print("[RAG] ✓ Qdrant connection verified")
    except Exception as e:
        status["error"] = f"Qdrant connection failed: {str(e)}"
        print(f"[RAG] ✗ Qdrant connection error: {e}")
        return status

    try:
        # Verify collection exists
        if client.collection_exists(CFG["collection"]):
            status["collection_exists"] = True
            collection_info = client.get_collection(CFG["collection"])
            print(f"[RAG] ✓ Collection '{CFG['collection']}' exists ({collection_info.points_count} points)")
        else:
            status["error"] = f"Collection '{CFG['collection']}' does not exist. Run embeddings indexing first."
            print(f"[RAG] ✗ Collection '{CFG['collection']}' not found")
            return status
    except Exception as e:
        status["error"] = f"Collection check failed: {str(e)}"
        print(f"[RAG] ✗ Collection check error: {e}")
        return status

    try:
        # Verify models are loaded
        if model is not None and reranker is not None:
            status["embeddings_loaded"] = True
            print("[RAG] ✓ Embedding and reranker models loaded")
        else:
            status["error"] = "Models not properly loaded"
            return status
    except Exception as e:
        status["error"] = f"Model check failed: {str(e)}"
        print(f"[RAG] ✗ Model check error: {e}")
        return status

    status["initialized"] = True
    status["error"] = None
    print("[RAG] ✓ RAG Pipeline fully initialized")
    return status


def get_db_status() -> dict[str, Any]:
    """Get current database and pipeline status without full initialization."""
    status = {
        "db_connected": False,
        "collection_exists": False,
        "collection_name": CFG["collection"],
        "qdrant_local_path": str(CFG["qdrant_local_path"]),
        "points_count": 0,
        "error": None,
    }

    try:
        client.get_collections()
        status["db_connected"] = True
    except Exception as e:
        status["error"] = f"Cannot connect to Qdrant: {str(e)}"
        return status

    try:
        if client.collection_exists(CFG["collection"]):
            status["collection_exists"] = True
            collection_info = client.get_collection(CFG["collection"])
            status["points_count"] = collection_info.points_count
        else:
            status["error"] = f"Collection '{CFG['collection']}' not found"
    except Exception as e:
        status["error"] = f"Collection check failed: {str(e)}"

    return status


def get_actual_filename(chunk_source: str) -> str:
    if chunk_source in FILE_MAPPING:
        return FILE_MAPPING[chunk_source]
    return f"{chunk_source}.pdf"


def load_parent_chunks(parent_ids: list[str]) -> dict[str, str]:
    parent_chunks: dict[str, str] = {}
    for parent_id in parent_ids:
        try:
            parent_file = CFG["parent_dir"] / f"{parent_id}.txt"
            if parent_file.exists():
                content = parent_file.read_text(encoding="utf-8")
                text = content.split("---\n", 1)[1].strip() if "---\n" in content else content.strip()
                parent_chunks[parent_id] = text
        except Exception as e:
            print(f"[RAG] Warning: could not load parent chunk {parent_id}: {e}")
    return parent_chunks


def sparse_search(query_sparse: dict, all_points: list, limit: int = 5) -> list[tuple[Any, float]]:
    scores: list[tuple[Any, float]] = []
    for point in all_points:
        sparse_payload = point.payload.get("sparse_embedding", {})
        score = sum(
            sparse_payload.get(token, 0) * query_sparse.get(token, 0)
            for token in query_sparse
            if token in sparse_payload
        )
        scores.append((point.id, score))
    return sorted(scores, key=lambda x: x[1], reverse=True)[:limit]


def hybrid_search(dense_scores: list[tuple[Any, float]], sparse_scores: list[tuple[Any, float]], alpha: float = 0.5, k: int = 60) -> list[tuple[Any, float]]:
    rrf_scores: dict[Any, float] = {}

    for rank, (point_id, _) in enumerate(dense_scores):
        rrf_scores[point_id] = alpha / (k + rank + 1)

    for rank, (point_id, _) in enumerate(sparse_scores):
        if point_id not in rrf_scores:
            rrf_scores[point_id] = 0.0
        rrf_scores[point_id] += (1 - alpha) / (k + rank + 1)

    return sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)


def get_parent_chunks_from_children(child_results: list) -> list[dict[str, str]]:
    parent_ids: set[str] = set()
    parent_info_map: dict[str, dict[str, str]] = {}

    for point in child_results:
        parent_id = point.payload.get("parent_id", "")
        if parent_id and parent_id not in parent_ids:
            parent_ids.add(parent_id)
            parent_info_map[parent_id] = {
                "source": point.payload.get("source", ""),
                "child_id": point.payload.get("child_id", ""),
            }

    parent_chunks_text = load_parent_chunks(list(parent_ids))

    parent_results: list[dict[str, str]] = []
    for parent_id in parent_ids:
        if parent_id in parent_chunks_text:
            parent_results.append(
                {
                    "parent_id": parent_id,
                    "text": parent_chunks_text[parent_id],
                    "source": parent_info_map[parent_id]["source"],
                    "sample_child": parent_info_map[parent_id]["child_id"],
                }
            )

    # Fallback: if a point does not map to a successfully loaded parent chunk, treat the child chunk itself as the retrieved unit.
    # This enables backward-compatibility with flat chunking collections (like the indexed db3 collection).
    used_parent_ids = {r["parent_id"] for r in parent_results}
    for point in child_results:
        pid = point.payload.get("parent_id", "")
        if not pid or pid not in used_parent_ids:
            fallback_id = pid if pid else f"fallback_{point.id}"
            parent_results.append({
                "parent_id": fallback_id,
                "text": point.payload.get("text", ""),
                "source": point.payload.get("source", ""),
                "sample_child": point.payload.get("child_id", point.payload.get("file", ""))
            })

    return parent_results


def rerank_parent_chunks(query: str, parent_chunks_list: list[dict[str, str]]) -> list[dict[str, Any]]:
    if not parent_chunks_list:
        return []

    pairs = [[query, chunk["text"]] for chunk in parent_chunks_list]
    rerank_scores = reranker.compute_score(pairs, normalize=True)
    ranked_indices = sorted(range(len(rerank_scores)), key=lambda i: rerank_scores[i], reverse=True)

    results: list[dict[str, Any]] = []
    for idx in ranked_indices:
        score = rerank_scores[idx]

        if (score >= RERANK_THRESHOLD and len(results) < RERANK_MAX_K) or len(results) < RERANK_MIN_K:
            results.append(
                {
                    "parent_id": parent_chunks_list[idx]["parent_id"],
                    "text": parent_chunks_list[idx]["text"],
                    "source": parent_chunks_list[idx]["source"],
                    "score": float(score),
                    "rank": len(results) + 1,
                }
            )

        if len(results) >= RERANK_MAX_K:
            break

    return results


def retrieve_context(query: str, num_context: int = 4) -> list[dict[str, Any]]:
    try:
        query_encoding = model.encode([query], batch_size=1, max_length=MAX_LENGTH)
        if query_encoding is None or "dense_vecs" not in query_encoding:
            return []

        query_dense = query_encoding["dense_vecs"][0].tolist()
        query_sparse: dict = {}

        lex_weights = query_encoding.get("lexical_weights")
        if lex_weights is not None:
            if isinstance(lex_weights, list) and len(lex_weights) > 0:
                try:
                    query_sparse = dict(lex_weights[0])
                except (TypeError, ValueError):
                    query_sparse = {}
            elif isinstance(lex_weights, dict):
                query_sparse = lex_weights

        dense_results = client.query_points(
            collection_name=CFG["collection"],
            query=query_dense,
            limit=max(20, num_context * 5),
        )
        if dense_results is None or not dense_results.points:
            return []

        dense_scores = [(p.id, p.score) for p in dense_results.points]
        if query_sparse:
            sparse_scores = sparse_search(query_sparse, dense_results.points, limit=max(20, num_context * 5))
            hybrid_scores = hybrid_search(dense_scores, sparse_scores, alpha=HYBRID_ALPHA)
        else:
            hybrid_scores = [(pid, score) for pid, score in dense_scores]

        candidate_child_points = [
            next((p for p in dense_results.points if p.id == point_id), None)
            for point_id, _ in hybrid_scores[: max(20, num_context * 5)]
        ]
        candidate_child_points = [p for p in candidate_child_points if p is not None]

        parent_chunks_list = get_parent_chunks_from_children(candidate_child_points)
        reranked_results = rerank_parent_chunks(query, parent_chunks_list)

        formatted_results: list[dict[str, Any]] = []
        for result in reranked_results[:num_context]:
            formatted_results.append(
                {
                    "parent_id": result["parent_id"],
                    "source": get_actual_filename(result["source"]),
                    "score": result["score"],
                    "text": result["text"],
                    "rank": result["rank"],
                    "point": type(
                        "Point",
                        (),
                        {
                            "payload": {
                                "text": result["text"],
                                "source": result["source"],
                                "parent_id": result["parent_id"],
                            }
                        },
                    )(),
                }
            )

        return formatted_results

    except Exception as e:
        print(f"[RAG] Retrieval error: {e}")
        return []


def generate_answer(query: str, context_results: list[dict[str, Any]]) -> str:
    if not context_results:
        return "No context available to generate an answer."

    context_text = "\n\n".join(
        [f"[Source: {r['source']}]\n{r.get('text', 'N/A')[:1000]}" for r in context_results[:RERANK_MAX_K]]
    )

    prompt = f"""You are a helpful assistant answering questions based on provided documents.

CONTEXT:
{context_text}

QUESTION: {query}

ANSWER:"""

    try:
        response = requests.post(
            f"http://{CFG['ollama_host']}:{CFG['ollama_port']}/api/generate",
            json={
                "model": CFG["ollama_model"],
                "prompt": prompt,
                "stream": False,
                "temperature": 0.3,
            },
            timeout=60,
        )

        if response.status_code == 200:
            return response.json().get("response", "Error: No response from model")
        return f"Error: LLM service returned {response.status_code}"

    except requests.exceptions.ConnectionError:
        return f"Error: Could not connect to LLM service at {CFG['ollama_host']}:{CFG['ollama_port']}. Is Ollama running?"
    except Exception as e:
        return f"Error: {str(e)}"


if __name__ == "__main__":
    test_query = "What are the main topics covered?"
    print(f"[RAG] Test query: {test_query}")
    hits = retrieve_context(test_query)
    print(f"[RAG] Retrieved {len(hits)} chunks")
    if hits:
        print(generate_answer(test_query, hits))
