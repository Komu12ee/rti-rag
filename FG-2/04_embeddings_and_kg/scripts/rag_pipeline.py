import os
import json
import atexit
import time
import sys
from pathlib import Path
import requests
from qdrant_client import QdrantClient
from FlagEmbedding import BGEM3FlagModel, FlagReranker

for stream_name in ("stdout", "stderr"):
    stream = getattr(sys, stream_name, None)
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

# ── Timing Utilities ───────────────────────────────────────────
_pipeline_start = None
_stage_times = {}

def _mark_time(stage_name):
    """Mark the current time for a stage and print elapsed time."""
    global _pipeline_start, _stage_times
    current_time = time.time()
    
    if _pipeline_start is None:
        _pipeline_start = current_time
        _stage_times[stage_name] = current_time
        print(f"⏱️ [{stage_name}] STARTED")
    else:
        if stage_name in _stage_times:
            elapsed = current_time - _stage_times[stage_name]
            print(f"⏱️ [{stage_name}] COMPLETED in {elapsed:.2f}s")
        _stage_times[stage_name] = current_time

def _print_timing_summary():
    """Print timing summary for entire pipeline."""
    global _pipeline_start
    if _pipeline_start is None:
        return
    total = time.time() - _pipeline_start
    print(f"\n{'='*70}")
    print(f"⏱️ TOTAL PIPELINE TIME: {total:.2f} seconds")
    print(f"{'='*70}\n")

# ── Configuration ──────────────────────────────────────────────
def _get_config():
    """Load configuration with environment variable overrides."""
    root = Path(__file__).resolve().parents[2]  # CHiPPY directory
    qdrant_mode = os.getenv("QDRANT_MODE", "local").lower()
    return {
        "chunk_dir": Path(os.getenv("CHIPPY_CHUNK_DIR", str(root.parent / "chunking" / "output_child_first"))),
        "collection": os.getenv("CHIPPY_QDRANT_COLLECTION", "db3"),
        "qdrant_mode": qdrant_mode,
        "qdrant_local_path": Path(
            os.getenv(
                "CHIPPY_QDRANT_LOCAL_PATH",
                str(root / "04_embeddings_and_kg" / "db" / "qdrant_local")
            )
        ),
        "qdrant_host": os.getenv("QDRANT_HOST", "localhost"),
        "qdrant_port": int(os.getenv("QDRANT_PORT", "6333")),
        "qdrant_api_key": os.getenv("QDRANT_API_KEY", None),
        "qdrant_timeout": int(os.getenv("QDRANT_TIMEOUT", "60")),
        "encode_batch_size": 8,
        "max_length": 1024,
        "qdrant_connect_retries": int(os.getenv("CHIPPY_QDRANT_CONNECT_RETRIES", "3")),
        "qdrant_connect_delay": float(os.getenv("CHIPPY_QDRANT_CONNECT_DELAY", "1.5")),
    }

CFG = _get_config()
CHUNK_DIR = CFG["chunk_dir"]
COLLECTION_NAME = CFG["collection"]
ENCODE_BATCH_SIZE = CFG["encode_batch_size"]
MAX_LENGTH = CFG["max_length"]

# ──────────────────────────────────────────────────────────────
# GROQ API Configuration (COMMENTED OUT - kept for future use)
# ──────────────────────────────────────────────────────────────
# GROQ_API_KEY = os.getenv("GROQ_API_KEY", None)
# GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
# GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# ──────────────────────────────────────────────────────────────
# SARVAM AI API Configuration (ACTIVE)
# ──────────────────────────────────────────────────────────────
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "sk_hhusezzy_cnfsLw6EbCOox523LJGXm15G")
SARVAM_MODEL = os.getenv("SARVAM_MODEL", "sarvam-105b")  # Sarvam AI's 105B model
SARVAM_API_URL = "https://api.sarvam.ai/v1/chat/completions"

# ── Retrieval Configuration ────────────────────────────────────
HYBRID_ALPHA = 0.6           # 0.0 = pure sparse, 1.0 = pure dense (0.6 = 60% dense, 40% sparse)
RERANK_MIN_K = 3             # Minimum results to return
RERANK_MAX_K = 6             # Maximum results to return
RERANK_THRESHOLD = 0.65      # Score threshold for inclusion
USE_MULTI_QUERY = True       # Enable multi-query retrieval for better coverage
USE_KNOWLEDGE_GRAPH = True   # Enable knowledge graph enhancement
KG_WEIGHT = 0.3              # Weight of KG in combined score (0-1)
KG_EXPANSION_DEPTH = 2       # Entity graph traversal depth

# ── Helper: Get file number from chunk source ───────────────────
def extract_file_number(chunk_source):
    """Extract file number from chunk source (e.g., 'output_corrected2' → 2)."""
    import re
    match = re.search(r'output_corrected(\d+)', chunk_source)
    if match:
        return int(match.group(1))
    return None

# ── Helper: Get actual file name from chunk metadata ───────────
def get_actual_filename(chunk_source):
    """Convert output_corrected* to actual file name using file numbers (file1.pdf, file2.pdf, etc.)."""
    file_num = extract_file_number(chunk_source)
    if file_num:
        return f"file{file_num}.pdf"
    return chunk_source + ".pdf"  # Fallback

# ── Helper: Extract highlighted excerpt from chunk text ─────────
def extract_highlighted_excerpt(chunk_text, query_words, max_length=300):
    """Extract the most relevant part of chunk text containing query words.
    
    Args:
        chunk_text: Full chunk text
        query_words: List of important words from the query
        max_length: Max length of excerpt
    
    Returns:
        Highlighted excerpt with query words in context
    """
    sentences = chunk_text.split('. ')
    best_sentences = []
    
    for sentence in sentences:
        sentence_lower = sentence.lower()
        if any(word.lower() in sentence_lower for word in query_words if len(word) > 3):
            best_sentences.append(sentence.strip())
    
    if best_sentences:
        excerpt = '. '.join(best_sentences[:2])  # Take first 2 matching sentences
    else:
        excerpt = chunk_text[:max_length]
    
    # Truncate if too long
    if len(excerpt) > max_length:
        excerpt = excerpt[:max_length].rsplit(' ', 1)[0] + '...'
    
    return excerpt.strip()

# Models and KG will be lazy-loaded on first retrieval to avoid heavy import-time work
model = None
reranker = None
kg_retriever = None
kg = None
_models_loaded = False

def ensure_models_loaded():
    """Load embedding, reranker and KG models on first use."""
    global model, reranker, kg_retriever, kg, _models_loaded
    if _models_loaded:
        return

    print("Loading embedding model (deferred)...")
    model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
    model.return_sparse = True

    print("Loading reranker model (deferred)...")
    reranker = FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=True)

    # Load Knowledge Graph (if available)
    if USE_KNOWLEDGE_GRAPH:
        try:
            from knowledge_graph import DocumentKnowledgeGraph
            from kg_retriever import KnowledgeGraphRetriever

            print("Loading knowledge graph (deferred)...")
            kg = DocumentKnowledgeGraph()
            kg_path = os.path.join(os.path.dirname(__file__), "knowledge_graph.json")

            if os.path.exists(kg_path):
                kg.load(kg_path)
                kg_retriever = KnowledgeGraphRetriever(kg, model)
                print(f"✓ Knowledge graph loaded: {len(kg.entities)} entities")
            else:
                print(f"⚠ Knowledge graph not found at {kg_path}")
                print("  Run 'python build_knowledge_graph.py' to create it")
                # fall back to disabling KG
                # keep USE_KNOWLEDGE_GRAPH as-is but avoid raising
                kg_retriever = None
        except ImportError as e:
            print(f"⚠ Could not import knowledge graph modules: {e}")
            kg_retriever = None

    _models_loaded = True

client = None


def _connect_qdrant_once():
    """Create a Qdrant client using the configured local or remote mode."""
    if CFG["qdrant_mode"] == "remote":
        print(f"Connecting to remote Qdrant at {CFG['qdrant_host']}:{CFG['qdrant_port']}...")
        qdrant = QdrantClient(
            host=CFG["qdrant_host"],
            port=CFG["qdrant_port"],
            api_key=CFG["qdrant_api_key"],
            timeout=CFG["qdrant_timeout"],
        )
        qdrant.get_collections()
        print(f"✓ Connected to remote Qdrant at {CFG['qdrant_host']}:{CFG['qdrant_port']}")
        return qdrant

    print(f"Connecting to local Qdrant at {CFG['qdrant_local_path']}...")
    CFG["qdrant_local_path"].mkdir(parents=True, exist_ok=True)
    qdrant = QdrantClient(path=str(CFG["qdrant_local_path"]))
    qdrant.get_collections()
    print("✓ Connected to local embedded Qdrant")
    return qdrant


def ensure_qdrant_client():
    """Create the module-level Qdrant client on demand with a short retry for stale locks."""
    global client
    if client is not None:
        return client

    last_error = None
    for attempt in range(1, CFG["qdrant_connect_retries"] + 1):
        try:
            client = _connect_qdrant_once()
            return client
        except Exception as e:
            last_error = e
            message = str(e)
            if "already accessed by another instance" in message and attempt < CFG["qdrant_connect_retries"]:
                wait_seconds = CFG["qdrant_connect_delay"] * attempt
                print(
                    f"[RAG] Local Qdrant is still locked; retrying in {wait_seconds:.1f}s "
                    f"({attempt}/{CFG['qdrant_connect_retries']})..."
                )
                time.sleep(wait_seconds)
                continue
            break

    raise RuntimeError(
        f"Unable to initialize Qdrant in {CFG['qdrant_mode']} mode: {last_error}"
    ) from last_error


def _cleanup_qdrant():
    """Explicitly close Qdrant client on exit to avoid shutdown import errors."""
    try:
        if client is not None:
            client.close()
    except Exception:
        pass  # Suppress cleanup errors during shutdown


atexit.register(_cleanup_qdrant)

# ── Validate Sarvam AI Configuration ─────────────────────────
if not SARVAM_API_KEY:
    print("⚠ WARNING: SARVAM_API_KEY not set. Set it via environment variable.")
    print("  Add to your terminal: $env:SARVAM_API_KEY='your-api-key-here'")
else:
    print(f"✓ Sarvam AI configured with model: {SARVAM_MODEL}")

# # ── Validate Groq Configuration (COMMENTED OUT) ──────────────
# if not GROQ_API_KEY:
#     print("⚠ WARNING: GROQ_API_KEY not set. Set it via environment variable.")
#     print("  Add to your terminal: $env:GROQ_API_KEY='your-api-key-here'")
# else:
#     print(f"✓ Groq API configured with model: {GROQ_MODEL}")

# ── Helper: Sparse search ──────────────────────────────────────
def sparse_search(query_sparse, all_points, limit=5):
    """Score points based on sparse embeddings overlap."""
    scores = []
    for point in all_points:
        sparse_payload = point.payload.get("sparse_embedding", {})
        score = sum(sparse_payload.get(token, 0) * query_sparse.get(token, 0) 
                   for token in query_sparse if token in sparse_payload)
        scores.append((point.id, score))
    return sorted(scores, key=lambda x: x[1], reverse=True)[:limit]

# ── Helper: Expand query into multiple perspectives ────────────
def expand_query(original_query):
    """Generate multiple query variations to improve retrieval coverage.
    
    Uses keyword expansion and perspective shifts:
    - Original query
    - Query + context keywords (approval, implementation, decision, etc.)
    - Query + document type keywords (agenda, minutes, meeting, etc.)
    - Query with synonyms
    """
    variations = [original_query]  # Always include original
    
    # Add context-specific variations for government documents
    context_keywords = ["approval", "decision", "implementation", "status", "progress"]
    doc_keywords = ["meeting", "agenda", "minutes", "committee", "approval"]
    
    for keyword in context_keywords:
        if keyword not in original_query.lower():
            variations.append(f"{original_query} {keyword}")
    
    for keyword in doc_keywords:
        if keyword not in original_query.lower():
            variations.append(f"{original_query} {keyword}")
    
    # Add detail-focused variations
    variations.append(f"{original_query} details implementation")
    variations.append(f"{original_query} decision taken")
    
    # Remove duplicates while preserving order
    seen = set()
    unique_variations = []
    for v in variations:
        v_lower = v.lower()
        if v_lower not in seen:
            seen.add(v_lower)
            unique_variations.append(v)
    
    return unique_variations[:5]  # Cap at 5 variations to avoid excessive querying

# ── Helper: Single query retrieval ─────────────────────────────
def perform_single_retrieval(query):
    """Perform single query retrieval and return results."""
    try:
        ensure_models_loaded()
        qdrant = ensure_qdrant_client()

        # Encode query with explicit batch_size to ensure sparse embeddings are generated
        # Using batch_size=1 explicitly ensures consistent behavior with batch encoding
        query_encoding = model.encode(
            [query],
            batch_size=1,  # Explicit batch size for single query
            max_length=MAX_LENGTH
        )
        
        if query_encoding is None or "dense_vecs" not in query_encoding:
            return None
        
        dense_vecs = query_encoding.get("dense_vecs")
        if dense_vecs is None or len(dense_vecs) == 0:
            return None
        
        query_dense = dense_vecs[0].tolist()
        
        # Get lexical weights (sparse embeddings) if available
        query_sparse = {}
        lex_weights = query_encoding.get("lexical_weights")
        if lex_weights is not None and isinstance(lex_weights, list) and len(lex_weights) > 0:
            try:
                query_sparse = dict(lex_weights[0])
            except (TypeError, ValueError):
                # Fallback if conversion fails
                query_sparse = {}
        elif lex_weights is not None and isinstance(lex_weights, dict):
            # Sparse weights might be returned as dict directly
            query_sparse = lex_weights
        
        # Dense search
        dense_results = qdrant.query_points(
            collection_name=COLLECTION_NAME,
            query=query_dense,
            limit=20
        )
        
        if dense_results is None or not dense_results.points:
            return None
        
        return {
            "dense_results": dense_results,
            "dense_scores": [(p.id, p.score) for p in dense_results.points],
            "query_sparse": query_sparse
        }
    
    except Exception as e:
        print(f"  Single retrieval error: {e}")
        return None

# ── Helper: Multi-query retrieval ──────────────────────────────
def multi_query_retrieval(query):
    """Retrieve results using multiple query variations and merge them.
    
    Benefits:
    - Captures different aspects of the query
    - Better coverage of semantically related documents
    - More robust to query phrasing variations
    """
    _mark_time("MULTI_QUERY_RETRIEVAL")
    ensure_models_loaded()
    
    if not USE_MULTI_QUERY:
        # Fall back to single query
        result = perform_single_retrieval(query)
        if result is None:
            return None, []
        return result["dense_results"], result["dense_scores"], result["query_sparse"]
    
    # Expand query into multiple variations
    query_variations = expand_query(query)
    print(f"  🔍 Searching with {len(query_variations)} query variations...")
    
    # Collect results from all query variations
    all_dense_results = {}  # {point_id: point}
    aggregated_scores = {}  # {point_id: sum_of_scores}
    all_sparse_queries = {}
    
    for i, q_variant in enumerate(query_variations):
        retrieval_result = perform_single_retrieval(q_variant)
        if retrieval_result is None:
            continue
        
        dense_results = retrieval_result["dense_results"]
        dense_scores = retrieval_result["dense_scores"]
        query_sparse = retrieval_result["query_sparse"]
        
        # Aggregate results
        for point in dense_results.points:
            all_dense_results[point.id] = point
        
        # Aggregate scores (later results still count, earlier have more weight)
        for point_id, score in dense_scores:
            if point_id not in aggregated_scores:
                aggregated_scores[point_id] = 0
            # Weight by position and query variation index
            aggregated_scores[point_id] += score * (1.0 / (i + 1))
        
        # Keep last query's sparse representation
        if query_sparse:
            all_sparse_queries = query_sparse
    
    if not all_dense_results:
        print("  Error: No results from multi-query retrieval.")
        return None, [], {}
    
    # Create mock result object with aggregated points
    class MockQueryResult:
        def __init__(self, points):
            self.points = points
    
    aggregated_points = list(all_dense_results.values())
    dense_results = MockQueryResult(aggregated_points)
    
    _mark_time("MULTI_QUERY_RETRIEVAL")
    return dense_results, list(aggregated_scores.items()), all_sparse_queries
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

# ── Helper: Rerank search results (Hybrid Threshold) ──────────
def rerank_results(query, candidate_points, min_k=3, max_k=6, threshold=0.65):
    """Rerank with hybrid method: threshold-based with min/max bounds.
    
    Args:
        query: Query string
        candidate_points: List of point objects
        min_k: Minimum results to return (default 3)
        max_k: Maximum results to return (default 6)
        threshold: Score threshold to include results (default 0.65)
    
    Logic:
        1. Include all results with score >= threshold
        2. But ensure at least min_k results
        3. Cap at max_k results
    """
    _mark_time("RERANKING")
    
    if not candidate_points:
        return []
    
    # Prepare query-document pairs for reranking
    pairs = []
    point_map = {}
    
    for idx, point in enumerate(candidate_points):
        text = point.payload.get("text", "")
        pairs.append([query, text])
        point_map[idx] = point
    
    # Score with reranker
    print(f"  📊 Reranking {len(pairs)} candidates...")
    rerank_scores = reranker.compute_score(pairs, normalize=True)
    
    # Sort by reranker scores (descending)
    ranked_indices = sorted(range(len(rerank_scores)), key=lambda i: rerank_scores[i], reverse=True)
    
    # Apply hybrid threshold logic
    results = []
    for rank, idx in enumerate(ranked_indices):
        score = rerank_scores[idx]
        
        # Include if:
        # 1. Score >= threshold AND results < max_k, OR
        # 2. results < min_k (ensure minimum)
        if (score >= threshold and len(results) < max_k) or len(results) < min_k:
            results.append({
                "point": point_map[idx],
                "score": score,
                "rank": len(results) + 1
            })
        # Stop if we've reached max_k
        if len(results) >= max_k:
            break
    
    _mark_time("RERANKING")
    return results

# ── Helper: Hybrid search using RRF ───────────────────────────
def hybrid_search(dense_scores, sparse_scores, alpha=0.5, k=60):
    """Combine dense and sparse scores using RRF (Reciprocal Rank Fusion)."""
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

# ── Helper: Retrieve context with optional KG enhancement ──────
def retrieve_context(query, num_context=5, use_kg=True):
    """Retrieve context documents with optional knowledge graph enhancement.
    
    Args:
        query: Search query
        num_context: Number of context results to return
        use_kg: Whether to use KG enhancement (if available)
    
    Returns:
        List of result dicts with 'point', 'score', 'rank', and optionally KG info
    """
    _mark_time("RETRIEVE_CONTEXT")
    try:
        # Step 1: Perform embedding-based retrieval
        print("🔍 Retrieving context...")
        
        # Multi-query retrieval (or single-query fallback)
        dense_results, aggregated_scores, query_sparse = multi_query_retrieval(query)
        
        if dense_results is None or not dense_results.points:
            print("Error: No results from retrieval.")
            return None
        
        # Sort aggregated scores
        dense_scores = sorted(aggregated_scores, key=lambda x: x[1], reverse=True)
        
        # Sparse search (if available)
        if query_sparse:
            sparse_scores = sparse_search(query_sparse, dense_results.points, limit=20)
            # Use configurable HYBRID_ALPHA
            hybrid_scores = hybrid_search(dense_scores, sparse_scores, alpha=HYBRID_ALPHA)
            print(f"  ⚡ Using hybrid search (α={HYBRID_ALPHA}: {int(HYBRID_ALPHA*100)}% dense, {int((1-HYBRID_ALPHA)*100)}% sparse)")
        else:
            hybrid_scores = [(pid, score) for rank, (pid, score) in enumerate(dense_scores)]
            print(f"  ⚡ Using dense-only search (sparse embeddings unavailable)")
        
        # Collect candidate points for reranking (from top 20 hybrid results)
        candidate_points = [
            next((p for p in dense_results.points if p.id == point_id), None)
            for point_id, _ in hybrid_scores[:20]
        ]
        candidate_points = [p for p in candidate_points if p is not None]
        
        # Step 2: Apply KG enhancement if enabled
        if use_kg and kg_retriever and USE_KNOWLEDGE_GRAPH:
            print("📚 Enhancing with knowledge graph...")
            
            # Convert points to embedding results format
            embedding_results = []
            for point in candidate_points:
                embedding_results.append({
                    'chunk_id': point.payload.get('file', '').replace('.txt', ''),
                    'text': point.payload.get('text', ''),
                    'source': point.payload.get('source', ''),
                    'score': next((s for pid, s in hybrid_scores if pid == point.id), 0.0),
                    'file': point.payload.get('file', '')
                })
            
            # Enhance with KG
            try:
                enhanced_results = kg_retriever.enhance_results(
                    embedding_results,
                    query,
                    kg_weight=KG_WEIGHT,
                    expansion_depth=KG_EXPANSION_DEPTH,
                    rerank=False  # Don't rerank yet
                )
                
                # Convert back to rerank format
                enhanced_points = []
                for enhanced in enhanced_results:
                    # Find original point
                    orig_point = next((p for p in candidate_points 
                                      if p.payload.get('file', '').replace('.txt', '') == enhanced.chunk_id), None)
                    if orig_point:
                        enhanced_points.append({
                            "point": orig_point,
                            "score": enhanced.embedding_score,
                            "combined_score": enhanced.combined_score,
                            "kg_score": enhanced.kg_score,
                            "entities": enhanced.entities,
                            "related_entities": enhanced.related_entities,
                            "rank": 0  # Placeholder, will be set after reranking
                        })
                
                candidate_points = [r["point"] for r in enhanced_points]
                print(f"  ✓ Enhanced {len(enhanced_points)} results with KG")
                
            except Exception as e:
                print(f"  ⚠ KG enhancement failed: {e}, continuing with embedding results...")
                enhanced_points = None
        else:
            enhanced_points = None
        
        # ════════════════════════════════════════════════════════════════════
        # RERANKING DISABLED FOR PERFORMANCE
        # Reason: Hindi embeddings are excellent quality (0.86+ scores)
        # Reranking adds <5% quality improvement but costs 62+ seconds
        # To re-enable: uncomment the code below
        # ════════════════════════════════════════════════════════════════════
        
        # Step 3: Rerank results with reranker [DISABLED]
        # print("🔄 Reranking results...")
        # reranked_results = rerank_results(query, candidate_points, 
        #                                  min_k=RERANK_MIN_K, 
        #                                  max_k=RERANK_MAX_K, 
        #                                  threshold=RERANK_THRESHOLD)
        # 
        # # Step 4: Merge KG information if available
        # if enhanced_points:
        #     for result in reranked_results:
        #         # Find matching enhanced result
        #         for enhanced in enhanced_points:
        #             if enhanced["point"].id == result["point"].id:
        #                 result["kg_score"] = enhanced.get("kg_score", 0.0)
        #                 result["entities"] = enhanced.get("entities", [])
        #                 result["related_entities"] = enhanced.get("related_entities", {})
        #                 break
        #         else:
        #             # Fallback if not found
        #             result["kg_score"] = 0.0
        #             result["entities"] = []
        #             result["related_entities"] = {}
        # 
        # return reranked_results[:num_context]
        
        # ════════════════════════════════════════════════════════════════════
        # ALTERNATIVE: Use hybrid search results directly (no reranking)
        # ════════════════════════════════════════════════════════════════════
        print("⚡ Using hybrid search results directly (reranking disabled)")
        
        # Convert hybrid scores to result format
        results = []
        for rank, (point_id, score) in enumerate(hybrid_scores[:num_context], 1):
            # Find the point with this ID
            point = next((p for p in dense_results.points if p.id == point_id), None)
            if point:
                result = {
                    "point": point,
                    "score": score,
                    "rank": rank
                }
                
                # Add KG information if available
                if enhanced_points:
                    for enhanced in enhanced_points:
                        if enhanced["point"].id == point_id:
                            result["kg_score"] = enhanced.get("kg_score", 0.0)
                            result["entities"] = enhanced.get("entities", [])
                            result["related_entities"] = enhanced.get("related_entities", {})
                            break
                    else:
                        result["kg_score"] = 0.0
                        result["entities"] = []
                        result["related_entities"] = {}
                else:
                    result["kg_score"] = 0.0
                    result["entities"] = []
                    result["related_entities"] = {}
                
                results.append(result)
        
        _mark_time("RETRIEVE_CONTEXT")
        return results
    
    except Exception as e:
        print(f"Retrieval error: {e}")
        import traceback
        traceback.print_exc()
        _mark_time("RETRIEVE_CONTEXT")
        return None

# ── Helper: Generate answer with Llama 3.3 70B via Groq API ─────
def generate_answer(query, context_results):
    """Generate answer using Sarvam AI API with retrieved context.
    
    Enhanced with knowledge graph information when available:
    - Mentions key entities found in results
    - Uses entity relationships for better context
    - Improves answer grounding with KG data
    - Shows source PDFs and highlighted excerpts
    """
    _mark_time("ANSWER_GENERATION")
    
    if not context_results:
        return "No context found to generate an answer."
    
    if not SARVAM_API_KEY:
        return "Error: SARVAM_API_KEY not configured. Please set the environment variable SARVAM_API_KEY."
    
    # Extract query words for highlighting
    query_words = [w for w in query.lower().split() if len(w) > 3]
    
    # Build context string from retrieved documents with source PDFs and highlights
    context_parts = []
    source_references = []  # Store source PDF references
    all_entities = set()  # Collect all entities from results
    
    for i, r in enumerate(context_results, 1):
        source = r['point'].payload.get('source', '')
        actual_pdf = get_actual_filename(source)
        text = r['point'].payload['text']
        
        # Track source PDFs
        if actual_pdf not in source_references:
            source_references.append(actual_pdf)
        
        # Add KG entities info if available
        entities_info = ""
        if "entities" in r and r.get("entities"):
            entities = r["entities"][:3]  # Top 3 entities
            entities_info = f" [Entities: {', '.join(entities)}]"
            all_entities.update(r.get("entities", []))
        
        # Format context with source PDF and FULL CHUNK TEXT (not excerpt)
        # Send complete chunk to ensure LLM has all available context
        context_parts.append(
            f"[Source {i}: {actual_pdf}]{entities_info}\n{text}"
        )
    
    context_text = "\n\n".join(context_parts)
    sources_str = ", ".join(source_references)
    
    # Build prompt with entity context
    entity_context = ""
    if all_entities:
        entity_context = f"\n\nKey entities found: {', '.join(list(all_entities)[:10])}"
    
    system_content = f"""You are a helpful assistant that answers questions based on government and organizational documents. 
Answer the user's question based on the provided context and key entities found in the documents.
If the context doesn't contain the information, say so clearly.

IMPORTANT INSTRUCTIONS:
1. Always mention the specific source PDFs you referenced: {sources_str}
2. When citing information, explicitly mention which PDF it came from
3. Use the key entities to provide more contextual and accurate answers{entity_context}
4. Quote relevant sections when appropriate
5. Be precise and cite specific dates, decisions, or approvals when available
6. Format your response clearly with source references"""
    
    user_message = f"""Context from documents:
{context_text}

Question: {query}

Answer (make sure to cite sources):"""
    
    try:
        print(f"\n🤖 Generating answer with Sarvam AI ({SARVAM_MODEL})...")
        response = requests.post(
            SARVAM_API_URL,
            headers={
                "Authorization": f"Bearer {SARVAM_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": SARVAM_MODEL,
                "messages": [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_message}
                ],
                "temperature": 0.7,
                "max_tokens": 2048,
            },
            timeout=300  # 5 minute timeout
        )
        
        if response.status_code != 200:
            error_msg = response.text
            try:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", error_msg)
            except:
                pass
            return f"Error from Sarvam AI API: {response.status_code} - {error_msg}"
        
        result = response.json()
        answer = result.get("choices", [{}])[0].get("message", {}).get("content", "No response generated")
        
        # Append source information to the answer
        answer += f"\n\n**Sources used:**\n" + "\n".join([f"• {pdf}" for pdf in source_references])
        
        _mark_time("ANSWER_GENERATION")
        return answer
    
    except requests.exceptions.ConnectionError:
        _mark_time("ANSWER_GENERATION")
        return f"Error: Cannot connect to Sarvam AI API. Check your internet connection and SARVAM_API_KEY."
    except requests.exceptions.Timeout:
        _mark_time("ANSWER_GENERATION")
        return "Error: Sarvam AI API request timed out. Please try again."
    except Exception as e:
        _mark_time("ANSWER_GENERATION")
        return f"Error generating answer: {e}"
    
    # ── COMMENTED OUT GROQ CODE (for future use) ──────────────────
    # try:
    #     print("\n🤖 Generating answer with Groq (Llama 3.3 70B)...")
    #     response = requests.post(
    #         GROQ_API_URL,
    #         headers={
    #             "Authorization": f"Bearer {GROQ_API_KEY}",
    #             "Content-Type": "application/json"
    #         },
    #         json={
    #             "model": GROQ_MODEL,
    #             "messages": [
    #                 {"role": "system", "content": system_content},
    #                 {"role": "user", "content": user_message}
    #             ],
    #             "temperature": 0.7,
    #             "max_tokens": 2048,
    #         },
    #         timeout=300  # 5 minute timeout
    #     )
    #     
    #     if response.status_code != 200:
    #         error_msg = response.text
    #         try:
    #             error_data = response.json()
    #             error_msg = error_data.get("error", {}).get("message", error_msg)
    #         except:
    #             pass
    #         return f"Error from Groq API: {response.status_code} - {error_msg}"
    #     
    #     result = response.json()
    #     answer = result.get("choices", [{}])[0].get("message", {}).get("content", "No response generated")
    #     
    #     # Append source information to the answer
    #     answer += f"\n\n**Sources used:**\n" + "\n".join([f"• {pdf}" for pdf in source_references])
    #     
    #     return answer
    # 
    # except requests.exceptions.ConnectionError:
    #     return f"Error: Cannot connect to Groq API. Check your internet connection and GROQ_API_KEY."
    # except requests.exceptions.Timeout:
    #     return "Error: Groq API request timed out. Please try again."
    # except Exception as e:
    #     return f"Error generating answer: {e}"

# ── Main RAG Pipeline ──────────────────────────────────────────
def rag_query(query):
    """Full RAG pipeline: retrieve context → generate answer.
    
    Steps:
    1. Retrieve context using embeddings + optional KG enhancement
    2. Rerank with BGE-Reranker
    3. Generate answer using Qwen via Ollama
    """
    global _pipeline_start, _stage_times
    _pipeline_start = None
    _stage_times = {}
    
    print(f"\n📝 Query: {query}\n")
    
    # Step 1: Retrieve context with optional KG enhancement
    context_results = retrieve_context(query, num_context=5, use_kg=USE_KNOWLEDGE_GRAPH and kg_retriever is not None)
    
    if context_results is None:
        print("Failed to retrieve context.")
        return
    
    # Display retrieved context with KG information
    print(f"\n📚 Retrieved {len(context_results)} context documents:\n")
    for result in context_results:
        source = result['point'].payload.get('source', '')
        actual_filename = get_actual_filename(source)
        embedding_score = result.get('score', result.get('embedding_score', 0))
        
        # Show scores
        score_info = f"Embedding: {embedding_score:.4f}"
        if "kg_score" in result and result["kg_score"] > 0:
            score_info += f", KG: {result['kg_score']:.4f}"
        
        print(f"[Rank {result['rank']}] {actual_filename}")
        print(f"  Scores: {score_info}")
        
        # Show entities if available
        if "entities" in result and result.get("entities"):
            entities = result["entities"][:5]
            print(f"  Entities: {', '.join(entities)}")
        
        print(f"  {result['point'].payload['text'][:200]}...\n")
    
    # Step 2: Generate answer with KG awareness
    answer = generate_answer(query, context_results)
    
    print("\n" + "=" * 70)
    print(answer)
    print("=" * 70)
    
    _print_timing_summary()
    
    return answer

# ── Interactive Loop ───────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("🚀 RAG Pipeline: Qwen + Ollama + Knowledge Graph")
    print("=" * 70)
    
    retrieval_mode = "Hybrid (Embeddings + Knowledge Graph)" if (USE_KNOWLEDGE_GRAPH and kg_retriever) else "Embeddings Only"
    print(f"\nRetrieval Mode: {retrieval_mode}")
    print(f"Multi-Query: {'Enabled' if USE_MULTI_QUERY else 'Disabled'}")
    print(f"Reranker: BGE-Reranker v2-M3")
    print(f"LLM: Qwen (via Ollama)")
    print("\nType 'exit' to quit, 'help' for commands.\n")
    print("=" * 70 + "\n")
    
    while True:
        query = input("Enter your question: ").strip()
        
        if query.lower() == "exit":
            print("\nGoodbye! 👋\n")
            break
        elif query.lower() == "help":
            print("\n" + "=" * 70)
            print("COMMANDS:")
            print("=" * 70)
            print("  help          - Show this help message")
            print("  stats         - Show knowledge graph statistics")
            print("  config        - Show current configuration")
            print("  exit          - Exit the program")
            print("\nOtherwise, enter any question about your documents.")
            print("=" * 70 + "\n")
            continue
        elif query.lower() == "stats":
            if kg_retriever:
                print("\n" + "=" * 70)
                print("KNOWLEDGE GRAPH STATISTICS:")
                print("=" * 70)
                stats = kg_retriever.kg.get_graph_statistics()
                print(f"  Entities:              {stats['num_entities']:>10}")
                print(f"  Relationships:         {stats['num_relationships']:>10}")
                print(f"  Referenced Chunks:     {stats['num_chunks']:>10}")
                print(f"  Graph Density:         {stats['density']:>10.4f}")
                print(f"  Connected Components:  {stats['num_connected_components']:>10}")
                print(f"  Avg Node Degree:       {stats['avg_degree']:>10.2f}")
                print("=" * 70 + "\n")
            else:
                print("Knowledge graph not available.\n")
            continue
        elif query.lower() == "config":
            print("\n" + "=" * 70)
            print("CURRENT CONFIGURATION:")
            print("=" * 70)
            print(f"  Hybrid Alpha:          {HYBRID_ALPHA}")
            print(f"  Multi-Query:           {USE_MULTI_QUERY}")
            print(f"  Knowledge Graph:       {USE_KNOWLEDGE_GRAPH and kg_retriever is not None}")
            print(f"  KG Weight:             {KG_WEIGHT}")
            print(f"  KG Expansion Depth:    {KG_EXPANSION_DEPTH}")
            print(f"  Rerank Min K:          {RERANK_MIN_K}")
            print(f"  Rerank Max K:          {RERANK_MAX_K}")
            print(f"  Rerank Threshold:      {RERANK_THRESHOLD}")
            print("=" * 70 + "\n")
            continue
        elif not query:
            continue
        
        try:
            rag_query(query)
        except KeyboardInterrupt:
            print("\n\nInterrupted by user.\n")
        except Exception as e:
            print(f"Error processing query: {e}\n")
