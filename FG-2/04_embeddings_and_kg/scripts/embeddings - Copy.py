import os
import json
from pathlib import Path
from tqdm import tqdm
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct
from FlagEmbedding import BGEM3FlagModel, FlagReranker

# Docker-compatible path configuration
_SCRIPT_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent

CHUNK_DIR = Path(os.getenv("CHUNK_DIR", str(_PROJECT_ROOT / "03_chunking" / "output")))
PARENT_DIR = Path(os.getenv("PARENT_DIR", str(_PROJECT_ROOT / "03_chunking" / "output")))
JSON_DIR = Path(os.getenv("JSON_DIR", str(_PROJECT_ROOT / "04_embeddings_and_kg" / "data")))
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "db3")  # New collection for parent-child retrieval
UPSERT_BATCH_SIZE = 100
ENCODE_BATCH_SIZE = 8
MAX_LENGTH = 1024  # matches your chunk token size
FILES_MAPPING = Path(os.getenv("FILES_MAPPING", str(_PROJECT_ROOT / "files.txt")))

# ── Parent-Child relationship cache ────────────────────────────
CHUNK_HIERARCHY = {}  # Loaded from JSON files
PARENT_CHUNKS_CACHE = {}  # {parent_id: text}

# ── Retrieval Configuration ────────────────────────────────────
HYBRID_ALPHA = 0.6           # 0.0 = pure sparse, 1.0 = pure dense
RERANK_MIN_K = 2             # Minimum parent chunks to return
RERANK_MAX_K = 4             # Maximum parent chunks to return
RERANK_THRESHOLD = 0.60      # Score threshold for inclusion

# ── Load file mapping ──────────────────────────────────────────
def load_file_mapping(mapping_file):
    """Load mapping from files.txt to convert output_corrected* to actual file names."""
    mapping = {}
    try:
        with open(mapping_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or "-------->" not in line:
                    continue
                actual_name, output_name = line.split("-------->")
                actual_name = actual_name.strip()
                output_name = output_name.strip()
                # Extract just the "output_corrected1" part from "output_corrected1.pdf"
                output_base = output_name.replace(".pdf", "")
                mapping[output_base] = actual_name
    except Exception as e:
        print(f"Warning: Could not load file mapping from {mapping_file}: {e}")
    return mapping

# ── Load hierarchy from JSON files ─────────────────────────────
def load_chunk_hierarchy(json_dir):
    """Load parent-child relationships from hierarchy.json files in output_json."""
    hierarchy = {}
    try:
        for file in os.listdir(json_dir):
            if file.endswith("_hierarchy.json"):
                hierarchy_path = os.path.join(json_dir, file)
                with open(hierarchy_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for parent_info in data:
                        parent_id = parent_info["parent_id"]
                        hierarchy[parent_id] = {
                            "children": parent_info.get("children", []),
                            "source": parent_info.get("source", "")
                        }
                        # Also store inverse mapping: child -> parent
                        for child_id in parent_info.get("children", []):
                            if child_id not in hierarchy:
                                hierarchy[child_id] = {}
                            hierarchy[child_id]["parent_id"] = parent_id
        print(f"[Init] Loaded hierarchy from {json_dir}: {len(hierarchy)} entries")
    except Exception as e:
        print(f"[Init] Warning: Could not load hierarchy from {json_dir}: {e}")
    return hierarchy

# ── Parse chunk file to extract parent_id and type ─────────────
def parse_chunk_file(filepath):
    """Parse a chunk file to extract metadata."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    lines = content.split("\n", 10)  # Get first 10 lines for metadata
    metadata = {"text": content}
    
    for line in lines:
        if line.startswith("Parent ID:"):
            metadata["parent_id"] = line.replace("Parent ID:", "").strip()
        elif line.startswith("Child ID:"):
            metadata["child_id"] = line.replace("Child ID:", "").strip()
            metadata["is_child"] = True
        elif line.startswith("Source:"):
            metadata["source"] = line.replace("Source:", "").strip()
        elif line.startswith("Children:"):
            children_str = line.replace("Children:", "").strip()
            metadata["children"] = [c.strip() for c in children_str.split(",") if c.strip()]
    
    if "child_id" not in metadata:
        metadata["is_child"] = False
    
    return metadata

FILE_MAPPING = load_file_mapping(FILES_MAPPING)
CHUNK_HIERARCHY = load_chunk_hierarchy(JSON_DIR)

# ── Helper: Get actual file name from chunk metadata ───────────
def get_actual_filename(chunk_source):
    """Convert output_corrected* to actual filename using mapping."""
    if chunk_source in FILE_MAPPING:
        return FILE_MAPPING[chunk_source]
    return chunk_source + ".pdf"  # Fallback

# ── Load models ────────────────────────────────────────────────
print("Loading embedding model...")
model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
model.return_sparse = True  # Enable sparse embeddings generation

print("Loading reranker model...")
reranker = FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=True)

# ── Connect to Qdrant ─────────────────────────────────────────
print("Connecting to Qdrant...")
# Docker-friendly Qdrant connection
qdrant_host = os.getenv("QDRANT_HOST", "localhost")
qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
qdrant_mode = os.getenv("QDRANT_MODE", "local")

if qdrant_mode == "remote":
    # Remote Qdrant service (Docker)
    qdrant_api_key = os.getenv("QDRANT_API_KEY", None)
    client = QdrantClient(host=qdrant_host, port=qdrant_port, api_key=qdrant_api_key)
else:
    # Local embedded Qdrant
    client = QdrantClient("localhost", port=6333)

# ════════════════════════════════════════════════════════════════
# ║                    INDEXING PHASE (one time)                 ║
# ════════════════════════════════════════════════════════════════

if not client.collection_exists(COLLECTION_NAME):
    print(f"\n[INDEX] Collection '{COLLECTION_NAME}' not found. Starting indexing phase...\n")
    print("Creating collection...")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE)
    )

    # ── Read chunks (child chunks only) ───────────────────────
    chunks = []
    metadata = []

    print("Reading child chunk files...")
    for file in sorted(os.listdir(CHUNK_DIR)):
        if not file.endswith(".txt") or file.endswith("_hierarchy.json"):
            continue
        
        # Skip parent chunks, only index child chunks
        if "_child_" not in file:
            continue
        
        path = os.path.join(CHUNK_DIR, file)
        chunk_meta = parse_chunk_file(path)
        
        # Extract only the text content (skip metadata headers)
        text_content = chunk_meta.get("text", "").split("---\n", 1)
        if len(text_content) > 1:
            text_content = text_content[1].strip()
        else:
            text_content = text_content[0].strip()
        
        if not text_content:
            continue

        chunks.append(text_content)
        metadata.append({
            "source": chunk_meta.get("source", ""),
            "child_id": chunk_meta.get("child_id", file),
            "parent_id": chunk_meta.get("parent_id", ""),
            "file": file
        })

    print(f"Loaded {len(chunks)} chunks")

    # ── Generate embeddings ───────────────────────────────────────
    print("Generating embeddings (with sparse enabled)...")
    encoding_result = model.encode(
        chunks,
        batch_size=ENCODE_BATCH_SIZE,
        max_length=MAX_LENGTH
    )    
    if encoding_result is None:
        print("ERROR: Model encoding failed. Check your data and model configuration.")
        exit(1)
    
    if "dense_vecs" not in encoding_result or "lexical_weights" not in encoding_result:
        print(f"ERROR: Unexpected encoding format. Got keys: {encoding_result.keys()}")
        exit(1)
    
    dense_embeddings = encoding_result["dense_vecs"]
    sparse_embeddings = encoding_result["lexical_weights"]

    # ── Build points ──────────────────────────────────────────────
    points = []
    for i, (chunk, d_vector, s_embedding, meta) in enumerate(zip(chunks, dense_embeddings, sparse_embeddings, metadata)):
        payload = {
            "text": chunk,
            "source": meta["source"],
            "child_id": meta["child_id"],
            "parent_id": meta["parent_id"],
            "file": meta["file"]
        }
        # Only store sparse embeddings if they're available
        if s_embedding is not None:
            # Convert numpy values to native Python floats for JSON serialization
            sparse_dict = {}
            for token_id, score in s_embedding.items():
                sparse_dict[str(token_id)] = float(score)
            payload["sparse_embedding"] = sparse_dict
        
        points.append(
            PointStruct(
                id=i,
                vector=d_vector.tolist(),  # ensure plain list, not numpy array
                payload=payload
            )
        )

    # ── Upload in batches ─────────────────────────────────────────
    print("Uploading to Qdrant...")
    for i in tqdm(range(0, len(points), UPSERT_BATCH_SIZE), desc="Upserting batches"):
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=points[i:i + UPSERT_BATCH_SIZE]
        )

    print(f"\n[SUCCESS] Indexing complete — {len(points)} chunks stored with sparse embeddings enabled.\n")

else:
    print(f"✓ Using existing collection '{COLLECTION_NAME}'.\n")

# ── Helper: Load parent chunks from files ──────────────────────
def load_parent_chunks(parent_ids, chunk_dir):
    """Load parent chunk text from files by parent IDs."""
    parent_chunks = {}
    for parent_id in parent_ids:
        try:
            parent_file = os.path.join(chunk_dir, f"{parent_id}.txt")
            if os.path.exists(parent_file):
                with open(parent_file, "r", encoding="utf-8") as f:
                    content = f.read()
                # Extract text after the "---" separator
                if "---\n" in content:
                    text = content.split("---\n", 1)[1].strip()
                else:
                    text = content.strip()
                parent_chunks[parent_id] = text
        except Exception as e:
            print(f"Warning: Could not load parent chunk {parent_id}: {e}")
    return parent_chunks

# ── Helper: Sparse search (BM25-like scoring) ─────────────────
def sparse_search(query_sparse, all_points, limit=5):
    """Score points based on sparse embeddings overlap."""
    scores = []
    for point in all_points:
        sparse_payload = point.payload.get("sparse_embedding", {})
        score = sum(sparse_payload.get(token, 0) * query_sparse.get(token, 0) 
                   for token in query_sparse if token in sparse_payload)
        scores.append((point.id, score))
    return sorted(scores, key=lambda x: x[1], reverse=True)[:limit]

# ── Helper: Hybrid search with RRF (Reciprocal Rank Fusion) ────
def hybrid_search(dense_scores, sparse_scores, alpha=0.5, k=60):
    """Combine dense and sparse scores using RRF."""
    rrf_scores = {}
    
    # Add dense scores (RRF formula: 1 / (k + rank))
    for rank, (point_id, score) in enumerate(dense_scores):
        rrf_scores[point_id] = alpha / (k + rank + 1)
    
    # Add sparse scores
    for rank, (point_id, score) in enumerate(sparse_scores):
        if point_id not in rrf_scores:
            rrf_scores[point_id] = 0
        rrf_scores[point_id] += (1 - alpha) / (k + rank + 1)
    
    return sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

# ── Helper: Extract parent chunks from child results ──────────
def get_parent_chunks_from_children(child_results, chunk_dir):
    """
    Extract unique parent chunks from child chunk results.
    
    Args:
        child_results: List of retrieved child chunk points
        chunk_dir: Directory containing chunk files
    
    Returns:
        List of deduplicated parent chunks with metadata
    """
    parent_ids = set()
    parent_info_map = {}
    
    # Collect unique parent IDs from child chunks
    for point in child_results:
        parent_id = point.payload.get("parent_id", "")
        if parent_id and parent_id not in parent_ids:
            parent_ids.add(parent_id)
            parent_info_map[parent_id] = {
                "source": point.payload.get("source", ""),
                "child_id": point.payload.get("child_id", "")
            }
    
    # Load parent chunk texts
    parent_chunks_text = load_parent_chunks(list(parent_ids), chunk_dir)
    
    # Combine into result format
    parent_results = []
    for parent_id in parent_ids:
        if parent_id in parent_chunks_text:
            parent_results.append({
                "parent_id": parent_id,
                "text": parent_chunks_text[parent_id],
                "source": parent_info_map[parent_id]["source"],
                "sample_child": parent_info_map[parent_id]["child_id"]
            })
    
    return parent_results

# ── Helper: Rerank parent chunks using BGE-Reranker ────────────
def rerank_parent_results(query, parent_chunks, min_k=2, max_k=4, threshold=0.60):
    """Rerank parent chunks using BGE-Reranker.
    
    Args:
        query: Query string
        parent_chunks: List of parent chunk dicts with 'text' key
        min_k: Minimum results to return
        max_k: Maximum results to return
        threshold: Score threshold for inclusion
    
    Returns:
        List of reranked parent chunks with scores
    """
    if not parent_chunks:
        return []
    
    # Prepare query-document pairs for reranking
    pairs = []
    for chunk in parent_chunks:
        pairs.append([query, chunk["text"]])
    
    # Score with reranker
    rerank_scores = reranker.compute_score(pairs, normalize=True)
    
    # Sort by reranker scores (descending)
    ranked_indices = sorted(range(len(rerank_scores)), key=lambda i: rerank_scores[i], reverse=True)
    
    # Apply hybrid threshold logic
    results = []
    for idx in ranked_indices:
        score = rerank_scores[idx]
        
        # Include if:
        # 1. Score >= threshold AND results < max_k, OR
        # 2. results < min_k (ensure minimum)
        if (score >= threshold and len(results) < max_k) or len(results) < min_k:
            results.append({
                "parent_id": parent_chunks[idx]["parent_id"],
                "text": parent_chunks[idx]["text"],
                "source": parent_chunks[idx]["source"],
                "score": float(score),
                "rank": len(results) + 1
            })
        # Stop if we've reached max_k
        if len(results) >= max_k:
            break
    
    return results

# ════════════════════════════════════════════════════════════════
# ║                    QUERY PHASE (many times)                  ║
# ════════════════════════════════════════════════════════════════

print("Ready for queries. Type 'exit' to quit.\n")
while True:
    query = input("\nEnter query (or 'exit'): ").strip()
    if query.lower() == "exit":
        break
    if not query:
        continue

    try:
        # Encode query with explicit batch_size to ensure sparse embeddings are generated
        query_encoding = model.encode([query], batch_size=1, max_length=MAX_LENGTH)
        
        # Check if encoding succeeded
        if query_encoding is None:
            print("Search error: Query encoding returned None. Check your query and model status.")
            continue
        
        if "dense_vecs" not in query_encoding:
            print(f"Search error: No dense_vecs in encoding result. Got keys: {query_encoding.keys()}")
            continue
        
        dense_vecs = query_encoding.get("dense_vecs")
        
        if dense_vecs is None or len(dense_vecs) == 0:
            print("Search error: No dense vectors generated.")
            continue
        
        query_dense = dense_vecs[0].tolist()
        
        # Get lexical weights (sparse embeddings) if available
        query_sparse = {}
        lex_weights = query_encoding.get("lexical_weights")
        if lex_weights is not None:
            if isinstance(lex_weights, list) and len(lex_weights) > 0:
                try:
                    query_sparse = dict(lex_weights[0])
                except (TypeError, ValueError):
                    query_sparse = {}
            elif isinstance(lex_weights, dict):
                query_sparse = lex_weights
        
        if not query_sparse:
            print("  (Note: Sparse embeddings not available, using dense search only)")
        
        # ════════════════════════════════════════════════════════════
        # STEP 1: Dense search to retrieve child chunks
        # ════════════════════════════════════════════════════════════
        print("\n[Step 1] Retrieving child chunks...")
        dense_results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_dense,
            limit=20
        )
        
        if dense_results is None or not dense_results.points:
            print("Search error: No results from dense search.")
            continue
        
        dense_scores = [(p.id, p.score) for p in dense_results.points]
        child_chunks = dense_results.points
        
        # Sparse search (if lexical weights available)
        if query_sparse:
            sparse_scores = sparse_search(query_sparse, dense_results.points, limit=20)
            hybrid_scores = hybrid_search(dense_scores, sparse_scores, alpha=HYBRID_ALPHA)
            print(f"  ⚡ Using hybrid search (α={HYBRID_ALPHA}: {int(HYBRID_ALPHA*100)}% dense, {int((1-HYBRID_ALPHA)*100)}% sparse)")
        else:
            hybrid_scores = [(pid, score) for rank, (pid, score) in enumerate(dense_scores)]
            print(f"  ⚡ Using dense-only search (sparse embeddings unavailable)")
        
        # Collect candidate child points for next step
        candidate_child_points = [
            next((p for p in dense_results.points if p.id == point_id), None)
            for point_id, _ in hybrid_scores[:20]
        ]
        candidate_child_points = [p for p in candidate_child_points if p is not None]
        print(f"  ✓ Retrieved {len(candidate_child_points)} child chunks")
        
        # ════════════════════════════════════════════════════════════
        # STEP 2: Extract parent chunks from child chunks
        # ════════════════════════════════════════════════════════════
        print("\n[Step 2] Extracting parent chunks from children...")
        parent_chunks_list = get_parent_chunks_from_children(candidate_child_points, PARENT_DIR)
        print(f"  ✓ Extracted {len(parent_chunks_list)} unique parent chunks (deduplicated)")
        
        # ════════════════════════════════════════════════════════════
        # STEP 3: Rerank parent chunks
        # ════════════════════════════════════════════════════════════
        print("\n[Step 3] Reranking parent chunks...")
        reranked_parent_results = rerank_parent_results(
            query, 
            parent_chunks_list,
            min_k=RERANK_MIN_K,
            max_k=RERANK_MAX_K,
            threshold=RERANK_THRESHOLD
        )
        
        # ════════════════════════════════════════════════════════════
        # STEP 4: Display final results (ready for LLM)
        # ════════════════════════════════════════════════════════════
        print("\n" + "="*70)
        print("FINAL RESULTS (Parent Chunks - Ready for LLM)")
        print("="*70 + "\n")
        
        if not reranked_parent_results:
            print("No results found.")
        else:
            for result in reranked_parent_results:
                actual_filename = get_actual_filename(result["source"])
                print(f"[Rank {result['rank']}] Parent: {result['parent_id']}")
                print(f"Source: {actual_filename}")
                print(f"Score: {result['score']:.4f}")
                print(f"Preview: {result['text'][:400]}...")
                print("\n" + "-"*70 + "\n")

    except (KeyError, TypeError, AttributeError) as e:
        print(f"Search error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"Search error: {e}")
        import traceback
        traceback.print_exc()