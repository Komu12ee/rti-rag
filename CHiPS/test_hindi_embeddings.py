"""
Test the quality of BAAI/bge-m3 embeddings for Hindi queries.
Checks if embeddings capture semantic meaning for Hindi documents.
"""

import sys
from pathlib import Path
import numpy as np
from FlagEmbedding import BGEM3FlagModel
from qdrant_client import QdrantClient

# Setup paths
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT / '04_embeddings_and_kg' / 'scripts'))

print("=" * 80)
print("🧪 HINDI EMBEDDING QUALITY TEST")
print("=" * 80)

# Load model
print("\n📦 Loading BAAI/bge-m3 model...")
model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)

# Connect to Qdrant
print("🗄️ Connecting to Qdrant...")
client = QdrantClient(path=str(PROJECT_ROOT / "04_embeddings_and_kg" / "db" / "qdrant_local"))
collection_name = "db3"

print(f"\n📊 Testing embedding quality for Hindi queries...")
print("=" * 80)

# Test 1: Hindi query from user (Devanagari script)
hindi_query = "रु. 10 लाख तक के समस्त कार्यों को ऑफलाईन मैनुअल निविदा के माध्यम से तथा रु. 10 लाख से अधिक के कार्यों की समस्त निविदायें ई टेण्डरिंग ऑनलाईन) के माध्यम से क्रियान्वित किये जाने के संबंध में अनुमोदन"

# Test 2: English equivalent
english_query = "Approval for implementation of tender process for works up to 10 lakhs through offline manual tender and above 10 lakhs through online e-tendering"

# Test 3: Hindi + English mixed query
mixed_query = "रु. 10 लाख क्षमता tender decision taken"

test_queries = [
    ("Hindi (Devanagari)", hindi_query),
    ("English", english_query),
    ("Mixed Hindi+English", mixed_query),
]

print("\n🔍 TEST 1: Query Encoding Quality")
print("-" * 80)

for lang, query in test_queries:
    print(f"\n[{lang}]")
    print(f"Query: {query[:60]}..." if len(query) > 60 else f"Query: {query}")
    
    # Encode query
    encoding = model.encode([query], batch_size=1, max_length=1024)
    
    dense_vec = encoding.get("dense_vecs")[0]
    sparse_weights = encoding.get("lexical_weights")[0] if encoding.get("lexical_weights") else {}
    
    print(f"  ✓ Dense embedding: {len(dense_vec)} dimensions, norm={np.linalg.norm(dense_vec):.4f}")
    print(f"  ✓ Sparse weights: {len(sparse_weights)} tokens")
    print(f"  ✓ Top sparse tokens: {sorted(sparse_weights.items(), key=lambda x: x[1], reverse=True)[:5]}")

print("\n\n🔍 TEST 2: Retrieval Quality (Dense Search)")
print("-" * 80)

for lang, query in test_queries:
    print(f"\n[{lang}]")
    print(f"Query: {query[:60]}..." if len(query) > 60 else f"Query: {query}")
    
    # Encode and search
    encoding = model.encode([query], batch_size=1, max_length=1024)
    dense_vec = encoding.get("dense_vecs")[0].tolist()
    
    # Dense search
    results = client.query_points(
        collection_name=collection_name,
        query=dense_vec,
        limit=5
    )
    
    print(f"\n  Top 5 Retrieved Documents:")
    for rank, point in enumerate(results.points, 1):
        text = point.payload.get("text", "")[:80]
        source = point.payload.get("source", "unknown")
        print(f"    {rank}. [{source}] Score: {point.score:.4f}")
        print(f"       {text}...")

print("\n\n🔍 TEST 3: Hindi Document Representation")
print("-" * 80)

# Get a sample of Hindi documents from chunks
print("\nFetching sample documents from Qdrant...")
sample_points = client.scroll(collection_name, limit=10)[0]

hindi_docs = []
english_docs = []

for point in sample_points:
    text = point.payload.get("text", "")
    # Check if text contains Devanagari script
    if any("\u0900" <= c <= "\u097F" for c in text):
        hindi_docs.append((text[:100], point.payload.get("source", "unknown")))
    else:
        english_docs.append((text[:100], point.payload.get("source", "unknown")))

print(f"\n📄 Found: {len(hindi_docs)} Hindi documents, {len(english_docs)} English documents")

if hindi_docs:
    print("\nSample Hindi Documents:")
    for i, (text, source) in enumerate(hindi_docs[:3], 1):
        print(f"  {i}. [{source}] {text}...")
else:
    print("\n⚠️  No Hindi documents found in collection")

if english_docs:
    print("\nSample English Documents:")
    for i, (text, source) in enumerate(english_docs[:3], 1):
        print(f"  {i}. [{source}] {text}...")

print("\n\n🔍 TEST 4: Cross-Lingual Search (Can English query find Hindi docs?)")
print("-" * 80)

print("\nSearching for English query in collection...")
encoding = model.encode([english_query], batch_size=1, max_length=1024)
dense_vec = encoding.get("dense_vecs")[0].tolist()

results = client.query_points(
    collection_name=collection_name,
    query=dense_vec,
    limit=10
)

print(f"\nTop 10 results for English query:")
for rank, point in enumerate(results.points, 1):
    text = point.payload.get("text", "")
    source = point.payload.get("source", "unknown")
    # Check if Devanagari
    is_hindi = any("\u0900" <= c <= "\u097F" for c in text)
    lang_marker = "🇮🇳 Hindi" if is_hindi else "🇬🇧 English"
    print(f"  {rank}. [{lang_marker}] [{source}] Score: {point.score:.4f}")
    print(f"     {text[:60]}...")

print("\n" + "=" * 80)
print("📋 ANALYSIS")
print("=" * 80)

print("""
✅ BAAI/bge-m3 Capabilities:
  - Officially supports 111+ languages including Hindi (Devanagari script)
  - Designed for multilingual semantic search
  - Generates both dense (semantic) and sparse (lexical) embeddings
  - Cross-lingual retrieval: English query can find Hindi docs and vice versa

⚠️  HINDI vs ENGLISH QUALITY:
  If the retrieval scores above show:
  - Similar quality for Hindi and English queries → Embeddings are GOOD for Hindi
  - Lower quality for Hindi queries → Reranking is ESSENTIAL (don't skip)
  - Good English results but poor Hindi → Mixed quality (use reranking)

🎯 RERANKING DECISION RULE:
  - If Hindi retrieval quality ≥ 90% of English → Skip reranking safely
  - If Hindi retrieval quality < 90% of English → Keep reranking (essential)
  - If documents are mostly mixed Hindi/English → Reranking provides value
""")

print("\n" + "=" * 80)
print("✅ Test complete. Review results above to decide on reranking.")
print("=" * 80)
