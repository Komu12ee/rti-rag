"""
RAG Pipeline Web UI
Simple Flask-based interface for document question-answering
"""

import os
import sys
import importlib.util
import time
from flask import Flask, request, jsonify, send_file
from datetime import datetime
from pathlib import Path

for stream_name in ('stdout', 'stderr'):
    stream = getattr(sys, stream_name, None)
    if hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8', errors='replace')



# Add parent directory to path for imports
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / '04_embeddings_and_kg' / 'scripts'))

# Dynamically find RAG pipeline module - works for both local and Docker
def _find_rag_module():
    """Find and import RAG pipeline module from various possible locations."""
    _candidate_paths = [
        PROJECT_ROOT / '04_embeddings_and_kg' / 'scripts' / 'rag_pipeline.py',
    ]
    
    for path in _candidate_paths:
        path = Path(path)
        if path.exists():
            print(f"[Web UI] Found RAG module at: {path}")
            spec = importlib.util.spec_from_file_location("rag_pipeline", str(path))
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules["rag_pipeline"] = module
                spec.loader.exec_module(module)
                return module
    
    raise ImportError("rag_pipeline.py not found in expected locations")


def _build_initialize_pipeline(rag_module):
    """Create a compatibility initializer when rag_pipeline.py does not expose one."""
    def _initialize_pipeline():
        status = {
            'initialized': False,
            'qdrant_connected': False,
            'collection_exists': False,
            'embeddings_loaded': False,
            'error': None,
        }

        client = getattr(rag_module, 'client', None)
        collection_name = getattr(rag_module, 'COLLECTION_NAME', None)
        if collection_name is None and hasattr(rag_module, 'CFG'):
            collection_name = rag_module.CFG.get('collection')

        try:
            if client is None:
                status['error'] = 'RAG client is not initialized'
                return status

            client.get_collections()
            status['qdrant_connected'] = True
        except Exception as e:
            status['error'] = f'Qdrant connection failed: {e}'
            return status

        try:
            if collection_name and client.collection_exists(collection_name):
                status['collection_exists'] = True
            else:
                status['error'] = f"Collection '{collection_name}' does not exist" if collection_name else 'Collection name unavailable'
                return status
        except Exception as e:
            status['error'] = f'Collection check failed: {e}'
            return status

        status['embeddings_loaded'] = True
        status['initialized'] = True
        return status

    return _initialize_pipeline


def _build_get_db_status(rag_module):
    """Create a compatibility DB status helper when rag_pipeline.py does not expose one."""
    def _get_db_status():
        status = {
            'db_connected': False,
            'collection_exists': False,
            'collection_name': None,
            'points_count': 0,
            'error': None,
        }

        client = getattr(rag_module, 'client', None)
        collection_name = getattr(rag_module, 'COLLECTION_NAME', None)
        if collection_name is None and hasattr(rag_module, 'CFG'):
            collection_name = rag_module.CFG.get('collection')
        status['collection_name'] = collection_name

        try:
            if client is None:
                status['error'] = 'RAG client is not initialized'
                return status

            client.get_collections()
            status['db_connected'] = True
        except Exception as e:
            status['error'] = f'Cannot connect to Qdrant: {e}'
            return status

        try:
            if collection_name and client.collection_exists(collection_name):
                status['collection_exists'] = True
                collection_info = client.get_collection(collection_name)
                status['points_count'] = collection_info.points_count
            else:
                status['error'] = f"Collection '{collection_name}' not found" if collection_name else 'Collection name unavailable'
        except Exception as e:
            status['error'] = f'Collection check failed: {e}'

        return status

    return _get_db_status


try:
    _rag_module = _find_rag_module()

    retrieve_context = _rag_module.retrieve_context
    generate_answer = _rag_module.generate_answer
    get_actual_filename = getattr(_rag_module, 'get_actual_filename', lambda chunk_source: f'{chunk_source}.pdf')
    initialize_pipeline = getattr(_rag_module, 'initialize_pipeline', None) or _build_initialize_pipeline(_rag_module)
    get_db_status = getattr(_rag_module, 'get_db_status', None) or _build_get_db_status(_rag_module)
    RAG_AVAILABLE = True
except Exception as e:
    print(f"Warning: Could not import RAG pipeline: {e}")
    RAG_AVAILABLE = False
    initialize_pipeline = None
    get_db_status = None

# Initialize Flask app
app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# Store settings
pipeline_initialized = False
qdrant_retry_attempted = False
kg_enabled = True
num_results = 3


def _is_qdrant_connection_failure(error_text):
    """Return True when the error likely indicates Qdrant connectivity failure."""
    if not error_text:
        return False

    msg = str(error_text).lower()
    keywords = [
        "qdrant connection failed",
        "cannot connect to qdrant",
        "connection refused",
        "failed to connect",
    ]
    return any(k in msg for k in keywords)


def _retry_initialize_once_on_qdrant_failure(error_text):
    """Attempt a single re-initialization after a Qdrant connection failure."""
    global qdrant_retry_attempted, pipeline_initialized

    if qdrant_retry_attempted:
        return None
    if not _is_qdrant_connection_failure(error_text):
        return None
    if not RAG_AVAILABLE or initialize_pipeline is None:
        return None

    qdrant_retry_attempted = True
    print("[Web UI] Qdrant connection failed. Retrying pipeline initialization once...")

    retry_result = initialize_pipeline()
    if retry_result.get('initialized'):
        pipeline_initialized = True
        print("[Web UI] One-time retry succeeded.")
    else:
        print(f"[Web UI] One-time retry failed: {retry_result.get('error')}")

    return retry_result

@app.route('/api/health', methods=['GET'])
def health():
    """Check system health"""
    return jsonify({
        'status': 'ok',
        'rag_pipeline': 'available' if RAG_AVAILABLE else 'unavailable',
        'pipeline_initialized': pipeline_initialized,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/init', methods=['POST'])
def init():
    """Initialize RAG pipeline and verify database connection"""
    global pipeline_initialized
    
    if not RAG_AVAILABLE:
        return jsonify({
            'success': False,
            'error': 'RAG pipeline not available. Check imports and configuration.',
            'details': {}
        }), 503
    
    try:
        print("\n[Web UI] Initializing RAG pipeline...")
        init_result = initialize_pipeline()
        
        if init_result.get('initialized'):
            pipeline_initialized = True
            print("[Web UI] RAG pipeline initialization successful")
            return jsonify({
                'success': True,
                'message': 'RAG pipeline initialized successfully',
                'details': init_result,
            }), 200

        retry_result = _retry_initialize_once_on_qdrant_failure(init_result.get('error'))
        if retry_result and retry_result.get('initialized'):
            return jsonify({
                'success': True,
                'message': 'RAG pipeline initialized successfully after one retry',
                'details': retry_result,
                'retried_once': True,
            }), 200

        else:
            print(f"[Web UI] RAG pipeline initialization failed: {init_result.get('error')}")
            return jsonify({
                'success': False,
                'error': init_result.get('error', 'Initialization failed'),
                'details': init_result,
                'retried_once': retry_result is not None,
                'retry_details': retry_result,
            }), 400
            
    except Exception as e:
        print(f"[Web UI] Error during initialization: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Initialization error: {str(e)}',
            'details': {}
        }), 500

@app.route('/api/db-status', methods=['GET'])
def db_status():
    """Check database connection and collection status"""
    
    if not RAG_AVAILABLE:
        return jsonify({
            'success': False,
            'error': 'RAG pipeline not available',
            'db_connected': False,
            'collection_exists': False
        }), 503
    
    try:
        status = get_db_status()

        if not status.get('db_connected', False):
            retry_result = _retry_initialize_once_on_qdrant_failure(status.get('error'))
            if retry_result and retry_result.get('initialized'):
                status = get_db_status()

        return jsonify({
            'success': True,
            'db_connected': status.get('db_connected', False),
            'collection_exists': status.get('collection_exists', False),
            'collection_name': status.get('collection_name'),
            'points_count': status.get('points_count', 0),
            'error': status.get('error'),
            'retried_once': qdrant_retry_attempted,
        }), 200
        
    except Exception as e:
        print(f"[Web UI] Error checking DB status: {e}")
        return jsonify({
            'success': False,
            'error': f'DB status check failed: {str(e)}',
            'db_connected': False,
            'collection_exists': False
        }), 500

@app.route('/api/query', methods=['POST'])
def query():
    """Process a query"""
    query_start_time = time.time()
    
    if not RAG_AVAILABLE:
        return jsonify({
            'success': False,
            'error': 'RAG pipeline not available. Check imports and configuration.',
            'query': ''
        }), 503
    
    data = request.get_json()
    query_text = data.get('query', '').strip()
    num_context = data.get('num_results', num_results)
    
    if not query_text:
        return jsonify({
            'success': False,
            'error': 'Query cannot be empty',
            'query': ''
        }), 400
    
    try:
        print(f"\n⏱️ [FLASK] Total request start")
        print(f"[Web UI] Processing query: {query_text}")
        
        # Step 1: Retrieve context (parent chunks)
        print(f"[Web UI] Retrieving context...")
        retrieval_start = time.time()
        context_results = retrieve_context(query_text, num_context=num_context)
        retrieval_time = time.time() - retrieval_start
        print(f"⏱️ [FLASK] Retrieval completed in {retrieval_time:.2f}s")
        
        if context_results is None or len(context_results) == 0:
            return jsonify({
                'success': False,
                'error': 'No context documents found for this query',
                'query': query_text,
                'results': []
            }), 200
        
        # Step 2: Generate answer
        print(f"[Web UI] Generating answer...")
        answer_start = time.time()
        answer = generate_answer(query_text, context_results)
        answer_time = time.time() - answer_start
        print(f"⏱️ [FLASK] Answer generation completed in {answer_time:.2f}s")
        
        # Format results for frontend with actual PDF names and highlighted excerpts
        formatted_results = []
        query_words = [w for w in query_text.lower().split() if len(w) > 3]
        
        for result in context_results:
            point = result.get('point', {})
            source = point.payload.get('source', '') if hasattr(point, 'payload') else ''
            text = point.payload.get('text', '') if hasattr(point, 'payload') else ''
            
            # Get actual PDF name
            actual_pdf = _rag_module.get_actual_filename(source) if '_rag_module' in globals() else source
            
            # Extract highlighted excerpt
            from_rag = getattr(_rag_module, 'extract_highlighted_excerpt', None)
            if from_rag:
                excerpt = from_rag(text, query_words, max_length=250)
            else:
                excerpt = text[:250] + "..." if len(text) > 250 else text
            
            result_item = {
                'rank': result.get('rank', 0),
                'source': source,
                'actual_pdf': actual_pdf,  # New: Show actual PDF name
                'score': result.get('score', 0),
                'text': text,
                'excerpt': excerpt,  # New: Show highlighted excerpt
                'parent_id': result.get('parent_id', '')
            }
            
            formatted_results.append(result_item)
        
        total_time = time.time() - query_start_time
        print(f"[Web UI] Query processed successfully")
        print(f"⏱️ [FLASK] TOTAL PIPELINE TIME: {total_time:.2f}s\n")
        
        return jsonify({
            'success': True,
            'query': query_text,
            'answer': answer,
            'results': formatted_results,
            'result_count': len(formatted_results),
            'execution_time': f"{total_time:.2f}s"
        }), 200
    
    except Exception as e:
        print(f"[Web UI] Error processing query: {e}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'success': False,
            'error': f'Error processing query: {str(e)}',
            'query': query_text,
            'results': []
        }), 500

@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    """Get or update settings"""
    global kg_enabled, num_results
    
    if request.method == 'GET':
        return jsonify({
            'kg_enabled': kg_enabled,
            'num_results': num_results
        }), 200
    
    elif request.method == 'POST':
        data = request.get_json()
        
        if 'kg_enabled' in data:
            kg_enabled = data['kg_enabled']
        if 'num_results' in data:
            num_results = max(1, min(10, data['num_results']))  # Clamp between 1-10
        
        return jsonify({
            'success': True,
            'kg_enabled': kg_enabled,
            'num_results': num_results
        }), 200

@app.route('/api/examples', methods=['GET'])
def examples():
    """Return example queries"""
    examples_list = [
        "What approval was given in the recent meeting?",
        "Who leads the committee?",
        "What are the key financial decisions?",
        "Summarize the meeting agenda",
        "What are the next action items?",
        "What entities are mentioned in the documents?",
        "What was discussed about budget allocation?",
        "Tell me about the committee members",
    ]
    
    return jsonify({
        'examples': examples_list
    }), 200

@app.route('/01_preprocessing/used_files/<filename>', methods=['GET'])
def serve_pdf(filename):
    """Serve PDF files from used_files directory"""
    import os
    
    # Security: Only allow PDF files and alphanumeric filenames
    if not filename.endswith('.pdf'):
        return jsonify({'error': 'Only PDF files are allowed'}), 403
    
    # Prevent directory traversal attacks
    if '..' in filename or '/' in filename:
        return jsonify({'error': 'Invalid filename'}), 403
    
    pdf_path = PROJECT_ROOT / '01_preprocessing' / 'used_files' / filename
    
    if not pdf_path.exists():
        return jsonify({'error': f'PDF not found: {filename}'}), 404
    
    try:
        return send_file(str(pdf_path), mimetype='application/pdf')
    except Exception as e:
        print(f"[Web UI] Error serving PDF {filename}: {e}")
        return jsonify({'error': f'Error serving PDF: {str(e)}'}), 500

if __name__ == '__main__':
    print("\n" + "="*70)
    print("🚀 CHiPS-RAG Pipeline (Internal Backend)")
    print("="*70)
    print(f"\nRAG Pipeline Status: {'✅ Available' if RAG_AVAILABLE else '❌ Unavailable'}")
    print(f"Environment: {os.getenv('ENVIRONMENT', 'development')}")
    print("\nℹ️  This Flask server is INTERNAL ONLY.")
    print("   Authentication is handled by Express.js at :3000")
    
    flask_host = os.getenv('FLASK_HOST', '0.0.0.0')
    flask_port = int(os.getenv('FLASK_PORT', '5000'))
    flask_debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    print(f"\nStarting Flask server on http://{flask_host}:{flask_port} (debug: {flask_debug})")
    print("Press Ctrl+C to stop the server\n")
    
    app.run(debug=flask_debug, host=flask_host, port=flask_port, use_reloader=False)
