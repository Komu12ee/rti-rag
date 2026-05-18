# RAG Pipeline Performance Analysis

**Analysis Date:** Current  
**Scope:** Response generation pipeline (excludes OCR/chunking)  
**Status:** Investigation phase - NO CHANGES MADE YET

---

## 📊 Pipeline Overview

```
User Query (Flask /api/query)
    ↓
[1] Query Encoding (BAAI/bge-m3 embedding model)
    ├→ Multi-Query Expansion (if enabled)
    ├→ Dense embedding generation
    └→ Sparse embedding (lexical weights) generation
    ↓
[2] Retrieval Stage
    ├→ Dense search against Qdrant (160+ chunks)
    ├→ Sparse search (if sparse embeddings available)
    ├→ Hybrid RRF combination (60% dense, 40% sparse)
    └→ Top 20 candidates selected
    ↓
[3] Reranking Stage
    ├→ BGE-Reranker v2-M3 inference
    ├→ Threshold-based filtering (threshold=0.65)
    ├→ Min/Max bounds enforcement (min_k=3, max_k=6)
    └→ 3-6 results selected
    ↓
[4] Answer Generation
    ├→ Prompt construction + source references
    ├→ System message + user message assembly
    ├→ Full chunk text transmission (not excerpts)
    └→ Sarvam AI API call (sarvam-105b)
    ↓
Answer + Source References → UI Display
```

---

## 🔍 Component Breakdown & Bottleneck Analysis

### Stage 1: Query Encoding (CRITICAL - MULTI-QUERY MULTIPLIER)

**Models Used:**
- **BAAI/bge-m3** (FlagEmbedding library)
  - Model size: ~560M parameters (large, FP16 = ~1.1GB)
  - Uses: Dense + Sparse encoding in single call
  - Batch size: 8 (but typically 1 per variant)
  - Max length: 1024 tokens

**Process:**
1. **Single Query Encoding:** ~200-500ms
   - Encode query string
   - Generate dense vector (1024-dim)
   - Generate sparse embedding (lexical weights/BM25-style)
   
2. **Multi-Query Expansion:** 5 query variants (if enabled)
   - Original query: `{query}`
   - +Context variants: `{query} approval`, `{query} decision`, `{query} implementation`, etc.
   - +Document variants: `{query} meeting`, `{query} agenda`, etc.
   - **Each variant requires separate embedding call**
   - **5 queries × ~250ms = ~1,250ms** ⚠️ **MULTIPLIER BOTTLENECK**

**Configuration:**
```python
USE_MULTI_QUERY = True  # Line 51 - ENABLED
model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
model.return_sparse = True
MAX_LENGTH = 1024
ENCODE_BATCH_SIZE = 8
```

**Performance Impact:**
- ✅ With multi-query: ~1.5-2s (5 × embedding calls)
- ⚠️ **Without multi-query: ~300-500ms** (5x faster potential)
- Memory: ~1.1GB for model (loaded once at startup)

---

### Stage 2: Qdrant Retrieval (MODERATE)

**Configuration:**
```python
HYBRID_ALPHA = 0.6  # 60% dense, 40% sparse
COLLECTION_NAME = "db3"
Points in collection: 160+ chunks
Dense vector dim: 1024
```

**Process:**
1. **Dense Search:** ~50-100ms
   - Query vector shape: (1024,)
   - Search space: 160+ points
   - Returns: Top 20 candidates with scores
   - Uses Qdrant's HNSW index (approximate search)

2. **Sparse Search:** ~30-50ms
   - Lexical weight scoring over 160+ chunks
   - RRF (Reciprocal Rank Fusion) computation
   - Combine with dense scores (60/40 weighting)

3. **Multi-Query Aggregation:**
   - For 5 query variants: 5 × (dense + sparse) searches
   - Aggregation logic: Weighted score averaging by variant order
   - Final ranking: Top 20 candidates

**Bottleneck Analysis:**
- Vector database lookup is generally **fast** (<100ms)
- **Main cost: 5 × searches** due to multi-query
- Sparse search adds minimal overhead (10-20% extra)
- RRF computation: negligible (<5ms)

**Performance Impact:**
- Single query: ~50-100ms dense + ~30-50ms sparse = **~80-150ms**
- 5 query variants: **~400-750ms**
- With aggregation: **~450-800ms total**

---

### Stage 3: Reranking (MODERATE)

**Model Used:**
- **BAAI/bge-reranker-v2-m3** (FlagEmbedding library)
  - Model size: ~250M parameters (FP16 = ~500MB)
  - Input: 20 [query, chunk_text] pairs
  - Output: 20 relevance scores (normalized)
  - Uses cross-encoder architecture (expensive but accurate)

**Process:**
1. **Prepare Query-Doc Pairs:** ~10ms
   - 20 candidates × [query, text] = 20 pairs
   - Extract text from point payloads
   
2. **Reranker Inference:** ~150-300ms
   - Cross-encoder processes all 20 pairs
   - Produces normalized relevance scores
   - Sorting by score: ~5ms

3. **Threshold-Based Selection:** ~10ms
   - Apply threshold = 0.65
   - Enforce min_k=3, max_k=6
   - Select final 3-6 results

**Bottleneck Analysis:**
- Reranker is **computationally expensive**
- Cross-encoder architecture: **slower than bi-encoders**
- Processing 20 [query, text] pairs is non-trivial
- GPU would help significantly (currently likely CPU-bound)

**Performance Impact:**
- **~150-300ms per rerank call**
- Only runs once per query (not per variant)
- ✅ More efficient than running 5 separate rerankers
- **EXPECTED: ~150-300ms**

---

### Stage 4: Answer Generation (CRITICAL - NETWORK + REMOTE LLM)

**Model/API Used:**
- **Sarvam AI API** (sarvam-105b)
- Endpoint: `https://api.sarvam.ai/v1/chat/completions`
- API Key: `$env:SARVAM_API_KEY`
- Configuration:
  - max_tokens: 2048
  - temperature: 0.7
  - timeout: 300s (5 minutes)

**Process:**
1. **Prompt Construction:** ~20-50ms
   - System message with context instructions
   - User message with:
     - Retrieved context (3-6 chunks)
     - Full chunk text (not excerpts) - **MAXIMIZES LLM CONTEXT**
     - Source PDF references
     - Key entities (from KG if available)
   - Typical prompt size: 2,000-5,000 tokens

2. **HTTP Request to Sarvam AI:** ~500ms-3s
   - Network latency: ~100-500ms (round-trip)
   - LLM inference: ~500-2000ms (sarvam-105b model)
   - Streaming response processing
   - Typical total: **~1-3 seconds** ⚠️ **MAJOR BOTTLENECK**

3. **Response Processing:** ~50-100ms
   - Parse JSON response
   - Extract answer content
   - Append source references
   - Return to frontend

**Bottleneck Analysis:**
- **MOST SIGNIFICANT BOTTLENECK**
- Network latency is unavoidable (remote API)
- LLM inference time depends on:
  - Sarvam servers' load
  - Model size (sarvam-105b is large)
  - Token count of prompt + response
  - Response length (up to 2048 tokens)

**Performance Impact:**
- **~1,000-3,000ms (1-3 seconds)** ⚠️ **PRIMARY BOTTLENECK**
- Accounts for ~50-70% of total pipeline time
- Depends on external service (Sarvam AI availability/load)

---

## 📈 Total Pipeline Timing Estimates

### Current Configuration (Multi-Query ENABLED):

| Stage | Time (ms) | Percentage | Notes |
|-------|-----------|------------|-------|
| Query encoding (5 variants) | 1,000-1,500 | ~25% | BAAI/bge-m3 × 5 |
| Qdrant retrieval (5 searches) | 400-800 | ~10% | Dense + sparse |
| Reranking (20→6 candidates) | 150-300 | ~4% | BAAI/bge-reranker-v2-m3 |
| Sarvam AI API + inference | 1,000-3,000 | ~50-70% | **BOTTLENECK** |
| Overhead (prompt build, I/O, parsing) | 100-200 | ~3-5% | JSON ops, string building |
| **TOTAL PIPELINE** | **~2,650-5,800ms** | **100%** | **2.7-5.8 seconds** |

**Breakdown:**
- Best case: ~2.7s (fast network, low Sarvam load)
- Typical case: ~4s (normal conditions)
- Worst case: ~5.8s (slow network, high Sarvam load)

---

## 🎯 Bottleneck Summary (Ranked by Impact)

### 🔴 **Critical Bottleneck #1: Sarvam AI API + Remote LLM Inference**
- **Impact:** 50-70% of total time
- **Cause:** Network latency + remote LLM inference
- **Why it's unavoidable:** Uses external API service
- **Potential improvements:**
  - Use faster local LLM (Ollama) instead of remote API
  - Use smaller model (sarvam-7b or similar)
  - Cache answers for common questions
  
### 🟠 **Bottleneck #2: Multi-Query Expansion (5 variants)**
- **Impact:** ~25% of total time (~1-1.5s)
- **Cause:** BAAI/bge-m3 model requires 5 separate encoding passes
- **Where it happens:** Line 232-280 in rag_pipeline.py (`expand_query()` + `perform_single_retrieval()` loop)
- **Why it's expensive:** 
  - BAAI/bge-m3 is 560M parameters (large model)
  - Each variant requires full forward pass through encoder
  - 5× multiplier compounds the cost
- **Potential improvements:**
  - Batch encode all 5 queries together (instead of sequential)
  - Use smaller embedding model (already using M3, could use base or small)
  - Disable multi-query (trade: worse retrieval coverage)
  - Use query expansion without re-embedding (rule-based)

### 🟡 **Bottleneck #3: Reranking Infrastructure**
- **Impact:** ~4-6% of total time (~150-300ms)
- **Cause:** BAAI/bge-reranker-v2-m3 cross-encoder architecture
- **Where it happens:** Line 419-457 in rag_pipeline.py (`rerank_results()`)
- **Why it's expensive:**
  - Cross-encoder processes all [query, text] pairs
  - 560M parameters requires compute
  - Running on CPU likely (no GPU acceleration)
- **Potential improvements:**
  - Use GPU acceleration
  - Use lighter reranker (e.g., monoBERT)
  - Skip reranking for high-threshold dense scores
  - Reduce candidates before reranking (20→10)

### 🟢 **Manageable: Qdrant Retrieval**
- **Impact:** ~10% of total time (~400-800ms)
- **Cause:** 5× database searches due to multi-query
- **Status:** Normal and expected, inherent to approach
- **Note:** Single search is fast (~80-150ms), but × 5 variants adds up

### ✅ **Not a bottleneck: Model Loading**
- **Impact:** Happens once at startup (~2-5 seconds)
- **No per-query cost** (models in memory)
- **Total models loaded:**
  - BAAI/bge-m3 (560M, FP16 = ~1.1GB)
  - BAAI/bge-reranker-v2-m3 (250M, FP16 = ~500MB)
  - Total memory: ~1.6GB

---

## 📊 Embedding Models Deep Dive

### BAAI/bge-m3 (Query + Document Encoder)
```python
# Line 148 in rag_pipeline.py
model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
model.return_sparse = True  # Generate sparse embeddings
```

**Specifications:**
- **Purpose:** Multi-task embedding model (dense + sparse)
- **Model family:** BGE (BAAI General Embedding)
- **Size:** 560M parameters
- **Precision:** FP16 (float16) = ~1.1GB memory
- **Output:**
  - Dense vector: 1024 dimensions
  - Sparse embedding: BM25-style lexical weights (dict of token→weight)
  
**Strengths:**
- ✅ Generates both dense and sparse in one pass
- ✅ Supports 8K+ token length
- ✅ High quality BiLingual embeddings

**Weaknesses:**
- ❌ Large model (560M) → slower inference
- ❌ Multi-query × 5 makes it multiplicative bottleneck
- ❌ No built-in query optimization

**Usage in Pipeline:**
- Encodes each query variant separately
- Called 5 times (once per variant) in `multi_query_retrieval()`
- Typical latency: ~200-300ms per encode call

---

### BAAI/bge-reranker-v2-m3 (Relevance Scorer)
```python
# Line 151 in rag_pipeline.py
reranker = FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=True)
```

**Specifications:**
- **Purpose:** Cross-encoder for relevance scoring
- **Architecture:** Cross-encoder (processes [query, text] pairs together)
- **Size:** 250M parameters
- **Precision:** FP16 = ~500MB memory
- **Input:** List of [query, document_text] pairs
- **Output:** Normalized relevance scores (0-1)

**Strengths:**
- ✅ State-of-the-art relevance scoring
- ✅ Handles long documents (up to 512 tokens per pair)
- ✅ Multilingual support

**Weaknesses:**
- ❌ Cross-encoder is computationally expensive
- ❌ Quadratic complexity with pair count
- ❌ Slower than bi-encoders for large candidate sets
- ❌ Cannot be precomputed (must score per-query)

**Usage in Pipeline:**
- Scores 20 [query, chunk] pairs
- Threshold-based selection: keep scores ≥ 0.65
- Min/max bounds: 3-6 results
- Typical latency: ~150-300ms

**Configuration:**
```python
# Lines 41-44
RERANK_MIN_K = 3        # Minimum results (ensure coverage)
RERANK_MAX_K = 6        # Maximum results (control context size)
RERANK_THRESHOLD = 0.65 # Score threshold for inclusion
```

---

### Sarvam AI API (LLM Provider)
```python
# Lines 36-39
SARVAM_API_KEY = os.getenv('SARVAM_API_KEY')
SARVAM_MODEL = "sarvam-105b"
SARVAM_API_URL = "https://api.sarvam.ai/v1/chat/completions"
```

**Specifications:**
- **Provider:** Sarvam AI (Indian AI startup)
- **Model:** sarvam-105b (large language model)
- **Model size:** ~105 billion parameters
- **Architecture:** Instruction-tuned LLM
- **API Format:** OpenAI-compatible chat completions

**Configuration:**
```python
# Lines 667-677 in generate_answer()
response = requests.post(
    SARVAM_API_URL,
    json={
        "model": SARVAM_MODEL,
        "messages": [ system_content, user_content ],
        "temperature": 0.7,
        "max_tokens": 2048,
    },
    timeout=300  # 5 minute timeout
)
```

**Performance Characteristics:**
- **API Latency:** ~1-3 seconds per request
- **Response time factors:**
  - Network round-trip: ~100-500ms
  - Server inference: ~500-2000ms
  - Model loading (if not cached): negligible
  
**Bottleneck Analysis:**
- ✅ OpenAI-compatible format (easy to swap)
- ❌ Remote API = network-dependent
- ❌ Large model (105B) = slower inference
- ❌ Shared inference servers may have queuing delays

---

## 🔄 Retrieval Configuration Analysis

### Hybrid Search (RRF - Reciprocal Rank Fusion)
```python
# Line 46
HYBRID_ALPHA = 0.6  # 60% dense, 40% sparse
```

**How it works:**
1. Dense search: Top 20 by vector similarity
2. Sparse search: Top 20 by BM25/lexical scores
3. RRF combination: Reciprocal Rank Fusion
   - Dense score: α / (k + rank + 1) = 0.6 / (60 + rank + 1)
   - Sparse score: (1-α) / (k + rank + 1) = 0.4 / (60 + rank + 1)
   - Combined: sum of both

**Rationale:**
- Dense vectors capture semantic meaning
- Sparse embeddings capture exact keywords
- 60/40 split favors semantic understanding

**Trade-offs:**
- ✅ Better coverage than dense-only
- ✅ Handles keyword-based and semantic queries
- ❌ Requires maintaining 2 indices (dense + sparse)
- ❌ Adds ~30-50ms to retrieval (sparse search overhead)

---

### Multi-Query Expansion
```python
# Line 51
USE_MULTI_QUERY = True

# Lines 223-254
def expand_query(original_query):
    """Generate 5 query variations"""
    variations = [original_query]
    # + context keywords: approval, decision, implementation, status, progress
    # + doc keywords: meeting, agenda, minutes, committee, approval
    # + detail variations: "details implementation", "decision taken"
    return unique_variations[:5]  # Cap at 5
```

**What it does:**
- Takes original query
- Expands to 5 semantically related variations
- Example:
  - Original: "What decisions were made?"
  - Variant 1: "What decisions were made? approval"
  - Variant 2: "What decisions were made? implementation"
  - Variant 3: "What decisions were made? meeting"
  - Variant 4: "What decisions were made? details implementation"
  - Variant 5: "What decisions were made? decision taken"

**Rationale:**
- Improves retrieval recall (captures more relevant documents)
- Handles different phrasings of same intent
- Better for government documents (standardized terminology)

**Performance Impact:**
- ✅ Better/more diverse results
- ❌ **5× embedding calls** (~1-1.5s overhead)
- ❌ **5× Qdrant searches** (~400-800ms overhead)
- ❌ **Total: ~1.5-2.3s extra per query**

---

## 📋 Complete Configuration Summary

### File: `04_embeddings_and_kg/scripts/rag_pipeline.py`

**Retrieval Configuration (Lines 41-56):**
```python
RERANK_MIN_K = 3
RERANK_MAX_K = 6
RERANK_THRESHOLD = 0.65
COLLECTION_NAME = "db3"
K_RRF = 60
HYBRID_ALPHA = 0.6  # 60% dense, 40% sparse
USE_MULTI_QUERY = True
USE_KNOWLEDGE_GRAPH = False  # Import failed
KG_WEIGHT = 0.3
KG_EXPANSION_DEPTH = 2
MAX_LENGTH = 1024
ENCODE_BATCH_SIZE = 8
```

**Model Configurations (Lines 148-151):**
```python
model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
    - Dense: 1024-dim vectors
    - Sparse: BM25-style lexical weights
    - Batch size: 8 (per encode call)

reranker = FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=True)
    - Relevance scoring for [query, text] pairs
    - Normalized output (0-1)
    - Threshold: 0.65
```

**LLM Configuration (Lines 36-39, 667-677):**
```python
SARVAM_MODEL = "sarvam-105b"
SARVAM_API_URL = "https://api.sarvam.ai/v1/chat/completions"
SARVAM_API_KEY = os.getenv('SARVAM_API_KEY')

Request config:
  - Temperature: 0.7
  - Max tokens: 2048
  - Timeout: 300s
```

### File: `05_webui/app.py`

**Query Endpoint (Lines 312-350):**
- Retrieves context
- Generates answer
- Returns JSON response with sources

---

## 💡 Key Findings & Recommendations (NO CHANGES YET)

### Main Performance Bottlenecks (Ranked by Impact):

1. **🔴 Sarvam AI Remote API (50-70% of time)**
   - Recommendation: Consider Ollama + local LLM (if you have GPU)
   - Alternative: Keep remote but accept 1-3s latency as part of UX

2. **🟠 Multi-Query Expansion (25% of time)**
   - Current: 5 query variants × BAAI/bge-m3 encoding
   - Could optimize: Batch encode all 5 at once, or disable if acceptable
   - Trade-off: Fewer queries = worse retrieval recall

3. **🟡 Reranking Cross-Encoder (4-6% of time)**
   - Current: BAAI/bge-reranker-v2-m3 on 20 candidates
   - Already reasonably efficient
   - Could add GPU acceleration if available

### What's Working Well:

✅ **Hybrid retrieval (dense + sparse)** - good coverage  
✅ **Threshold-based reranking** - prevents irrelevant results  
✅ **Full chunk transmission to LLM** - maximizes context for answer quality  
✅ **Qdrant embedding database** - fast search on 160+ chunks  
✅ **Sarvam API** - reliable, though remote

---

## 🔬 Performance Testing Recommendations

To identify actual bottlenecks, add timing instrumentation:

```python
# At start of rag_query() function
import time
timing = {}

# Wrapper function for each stage:
start = time.time()
# ... stage code ...
timing['stage_name'] = time.time() - start

# Log results
print(f"Query encoding: {timing.get('encode', 0)*1000:.1f}ms")
print(f"Qdrant retrieval: {timing.get('retrieval', 0)*1000:.1f}ms")
print(f"Reranking: {timing.get('rerank', 0)*1000:.1f}ms")
print(f"Answer generation: {timing.get('answer', 0)*1000:.1f}ms")
```

This would give real measurements vs. these estimates.

---

## 📌 Questions for Next Phase

When you're ready to optimize, consider:

1. **Do you want to keep Sarvam AI or switch to local LLM?**
   - Sarvam: Easier, no GPU needed, but 1-3s latency
   - Local (Ollama): Faster, needs GPU, but more infrastructure

2. **Is multi-query expansion adding enough value?**
   - Pros: Better retrieval coverage
   - Cons: 25% time overhead (5× embeddings)
   - Can test by disabling and comparing answer quality

3. **Do you have GPU access?**
   - Could significantly accelerate embeddings + reranking
   - Sarvam API gains would be minimal (external API)

4. **What's your target response time?**
   - Current: 2.7-5.8s (mostly Sarvam AI)
   - With local LLM: Could be 1.5-3s (mostly embedding/reranking)
   - With optimization: Could be 0.5-1.5s (if aggressive)

