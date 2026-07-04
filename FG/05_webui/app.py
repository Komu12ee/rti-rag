"""
RAG Pipeline Web UI
Simple Flask-based interface for document question-answering
"""
from dotenv import load_dotenv
from services.hybrid_retriever import retrieve_from_all_sources
from services.query_scope import extract_current_user_question
from services.unified_answer_service import generate_unified_answer
from services.pio_pipeline import PIOPipelineError, analyze_pio_application
from services.pio_qdrant_retriever import retrieve_pio_directory_references
import os
import sys
import importlib.util
import json
import re
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
load_dotenv(SCRIPT_DIR / ".env")
from services.hybrid_retriever import retrieve_from_all_sources
from services.query_scope import extract_current_user_question
from services.unified_answer_service import generate_unified_answer

from services.hybrid_retriever import retrieve_from_all_sources
from services.query_scope import extract_current_user_question
from services.unified_answer_service import generate_unified_answer

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
        ensure_qdrant_client = getattr(rag_module, 'ensure_qdrant_client', None)
        collection_name = getattr(rag_module, 'COLLECTION_NAME', None)
        collection_names = getattr(rag_module, 'COLLECTION_NAMES', None)
        if collection_name is None and hasattr(rag_module, 'CFG'):
            collection_name = rag_module.CFG.get('collection')
        collection_names = collection_names or ([collection_name] if collection_name else [])

        try:
            if client is None and callable(ensure_qdrant_client):
                client = ensure_qdrant_client()

            if client is None:
                status['error'] = 'RAG client is not initialized'
                return status

            client.get_collections()
            status['qdrant_connected'] = True
        except Exception as e:
            status['error'] = f'Qdrant connection failed: {e}'
            return status

        try:
            available = [
                name for name in collection_names
                if client.collection_exists(name)
            ]
            if available:
                status['collection_exists'] = True
            else:
                status['error'] = (
                    f"None of the configured collections exist: {collection_names}"
                    if collection_names
                    else 'Collection name unavailable'
                )
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
            'collection_names': [],
            'collections': {},
            'points_count': 0,
            'error': None,
        }

        client = getattr(rag_module, 'client', None)
        ensure_qdrant_client = getattr(rag_module, 'ensure_qdrant_client', None)
        collection_name = getattr(rag_module, 'COLLECTION_NAME', None)
        collection_names = getattr(rag_module, 'COLLECTION_NAMES', None)
        if collection_name is None and hasattr(rag_module, 'CFG'):
            collection_name = rag_module.CFG.get('collection')
        collection_names = collection_names or ([collection_name] if collection_name else [])
        status['collection_name'] = collection_name
        status['collection_names'] = collection_names

        try:
            if client is None and callable(ensure_qdrant_client):
                client = ensure_qdrant_client()

            if client is None:
                status['error'] = 'RAG client is not initialized'
                return status

            client.get_collections()
            status['db_connected'] = True
        except Exception as e:
            status['error'] = f'Cannot connect to Qdrant: {e}'
            return status

        try:
            for name in collection_names:
                if not client.collection_exists(name):
                    status['collections'][name] = {
                        'exists': False,
                        'points_count': 0,
                    }
                    continue
                collection_info = client.get_collection(name)
                points_count = collection_info.points_count or 0
                status['collections'][name] = {
                    'exists': True,
                    'points_count': points_count,
                }
                status['points_count'] += points_count

            if any(item['exists'] for item in status['collections'].values()):
                status['collection_exists'] = True
            else:
                status['error'] = (
                    f"None of the configured collections exist: {collection_names}"
                    if collection_names
                    else 'Collection name unavailable'
                )
        except Exception as e:
            status['error'] = f'Collection check failed: {e}'

        return status

    return _get_db_status


_rag_module = None
retrieve_context = None
generate_answer = None
get_actual_filename = lambda chunk_source: f'{chunk_source}.pdf'
initialize_pipeline = None
get_db_status = None
RAG_AVAILABLE = False
_rag_import_error = None


def _load_rag_module():
    """Import the heavy RAG module on demand so the Flask server can start first."""
    global _rag_module, retrieve_context, generate_answer, get_actual_filename
    global initialize_pipeline, get_db_status, RAG_AVAILABLE, _rag_import_error

    if _rag_module is not None:
        return _rag_module

    try:
        _rag_module = _find_rag_module()

        retrieve_context = _rag_module.retrieve_context
        generate_answer = _rag_module.generate_answer
        get_actual_filename = getattr(_rag_module, 'get_actual_filename', lambda chunk_source: f'{chunk_source}.pdf')
        initialize_pipeline = getattr(_rag_module, 'initialize_pipeline', None) or _build_initialize_pipeline(_rag_module)
        get_db_status = getattr(_rag_module, 'get_db_status', None) or _build_get_db_status(_rag_module)
        RAG_AVAILABLE = True
        _rag_import_error = None
        return _rag_module
    except Exception as e:
        print(f"Warning: Could not import RAG pipeline: {e}")
        _rag_module = None
        retrieve_context = None
        generate_answer = None
        initialize_pipeline = None
        get_db_status = None
        RAG_AVAILABLE = False
        _rag_import_error = str(e)
        return None

# Initialize Flask app to serve frontend static assets directly
app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), 'nodejs', 'public'),
    static_url_path=''
)
app.config['JSON_SORT_KEYS'] = False

@app.route('/')
def serve_index():
    """Serve index.html from static folder"""
    return send_file(os.path.join(app.static_folder, 'index.html'))

@app.route('/auth/login', methods=['POST'])
def auth_login():
    """Dummy login route for front-end compatibility"""
    return jsonify({
        'success': True,
        'token': 'dummy-token',
        'user': {'username': 'admin'}
    }), 200

@app.route('/auth/logout', methods=['POST'])
def auth_logout():
    """Dummy logout route for front-end compatibility"""
    return jsonify({'success': True}), 200

# Store settings
pipeline_initialized = False
qdrant_retry_attempted = False
kg_enabled = True
num_results = 3


def safe_pdf_stem(actual_pdf: str) -> str:
    """Return a filename-only PDF stem suitable for artifact lookup."""
    filename = Path(actual_pdf).name
    return Path(filename).stem


def get_document_artifact_paths(actual_pdf: str):
    """Return the precomputed ingestion artifacts associated with a PDF."""
    pdf_stem = safe_pdf_stem(actual_pdf)
    stage2_dir = PROJECT_ROOT / "01_preprocessing" / "stage2_output" / pdf_stem
    return {
        "doc_id": pdf_stem,
        "stage2_dir": stage2_dir,
        "structured_md": stage2_dir / "structured.md",
        "structured_json": stage2_dir / "structured.json",
        "page_debug_dir": stage2_dir / "page_debug",
        "pdf_candidates": [
            PROJECT_ROOT / "01_preprocessing" / "cic_pdfs_past_cases" / f"{pdf_stem}.pdf",
            PROJECT_ROOT / "01_preprocessing" / "used_files" / f"{pdf_stem}.pdf",
        ],
    }


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
        'rag_pipeline': 'available',
        'rag_module_loaded': _rag_module is not None,
        'pipeline_initialized': pipeline_initialized,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/init', methods=['POST'])
def init():
    """Initialize RAG pipeline and verify database connection"""
    global pipeline_initialized
    
    if _load_rag_module() is None or initialize_pipeline is None:
        return jsonify({
            'success': False,
            'error': _rag_import_error or 'RAG pipeline not available. Check imports and configuration.',
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
    
    if _rag_module is None:
        return jsonify({
            'success': True,
            'error': 'RAG module has not been loaded yet',
            'db_connected': False,
            'collection_exists': False,
            'collection_name': None,
            'points_count': 0
        }), 200
    
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

def _retrieve_context_for_unified(
    query_text: str,
    num_context: int,
):
    """
    Load Qdrant RAG only when the resolved route actually needs legal retrieval.

    PostgreSQL-only and clarification queries do not require the heavy RAG module.
    """
    if _load_rag_module() is None or retrieve_context is None:
        raise RuntimeError(
            _rag_import_error
            or "RAG pipeline not available for legal retrieval."
        )

    return retrieve_context(
        query_text,
        num_context=num_context,
    )


def _retrieve_pio_directory_for_unified(
    query: str,
    decision,
    criteria,
    limit: int,
):
    """
    Reuse rag_pipeline's single BGE-M3 model and single Qdrant client.

    This is important when QDRANT_MODE=local: creating another QdrantClient
    against the same embedded storage can cause an "already accessed" lock.
    """
    rag_module = _load_rag_module()
    if rag_module is None:
        raise RuntimeError(
            _rag_import_error
            or "RAG module is unavailable for PIO directory fallback."
        )

    ensure_embedding = getattr(rag_module, "ensure_embedding_model_loaded", None)
    if callable(ensure_embedding):
        ensure_embedding()
    else:
        # Compatibility with an older rag_pipeline.py before the lightweight
        # embedding-only initializer was added.
        rag_module.ensure_models_loaded()

    qdrant_client = rag_module.ensure_qdrant_client()
    embedding_model = getattr(rag_module, "model", None)

    if embedding_model is None:
        raise RuntimeError("BGE-M3 embedding model was not initialized.")

    return retrieve_pio_directory_references(
        query=query,
        decision=decision,
        criteria=criteria,
        client=qdrant_client,
        embedding_model=embedding_model,
        limit=limit,
    )


def _format_unified_evidence_for_frontend(
    evidence_items: list[dict],
) -> list[dict]:
    """
    Keep one frontend result shape for:
    - PostgreSQL officer registry results
    - PIO directory Qdrant fallback results
    - legal Qdrant/PDF results
    """
    formatted_results = []

    for index, item in enumerate(evidence_items, start=1):
        metadata = item.get("metadata") or {}

        source_type = str(
            item.get("source_type") or "Unknown source"
        )
        mode = str(item.get("mode") or "")
        text = str(item.get("content") or "")

        raw_source = str(metadata.get("source") or "")
        source = raw_source or source_type

        actual_pdf = ""
        document_id = str(
            metadata.get("office_code")
            or metadata.get("email")
            or metadata.get("officer_record_id")
            or f"{mode.lower() or 'result'}-{index}"
        )

        structured_md_available = False
        structured_json_available = False
        structured_md_path = ""
        structured_json_path = ""

        # Only legal Qdrant results may have a linked PDF/document artifact.
        if mode == "LEGAL" and raw_source:
            try:
                candidate_pdf = get_actual_filename(raw_source)
                paths = get_document_artifact_paths(candidate_pdf)

                pdf_exists = any(
                    candidate.is_file()
                    for candidate in paths["pdf_candidates"]
                )

                if pdf_exists:
                    actual_pdf = candidate_pdf
                    document_id = paths["doc_id"]
                    structured_md_available = paths["structured_md"].exists()
                    structured_json_available = paths["structured_json"].exists()
                    structured_md_path = (
                        str(paths["structured_md"])
                        if structured_md_available
                        else ""
                    )
                    structured_json_path = (
                        str(paths["structured_json"])
                        if structured_json_available
                        else ""
                    )

            except Exception as error:
                print(
                    "[Web UI] Could not prepare legal artifact metadata: "
                    f"{error}"
                )

        excerpt = text[:250]
        if len(text) > 250:
            excerpt += "..."

        if source_type == "CG RTI Officer Registry":
            retrieval_collection = "postgresql_officer_registry"
        elif source_type == "CG RTI Officer Directory (Qdrant)":
            retrieval_collection = "pio_directory_qdrant"
        else:
            retrieval_collection = "legal_qdrant"

        formatted_results.append(
            {
                "rank": metadata.get("rank", index),
                "source": source,
                "actual_pdf": actual_pdf,
                "retrieval_collection": retrieval_collection,
                "document_id": document_id,
                "score": metadata.get("score", 0),
                "text": text,
                "excerpt": excerpt,
                "parent_id": metadata.get("parent_id", ""),
                "structured_md_available": structured_md_available,
                "structured_json_available": structured_json_available,
                "structured_md_path": structured_md_path,
                "structured_json_path": structured_json_path,
                "page_start": metadata.get("page_start"),
                "page_end": metadata.get("page_end"),
                "chunk_type": metadata.get("chunk_type", ""),
                "source_type": source_type,
                "mode": mode,

                # Officer values let app.js render a directory card rather than
                # offering irrelevant PDF buttons.
                "officer_name": metadata.get("officer_name", ""),
                "rti_role": metadata.get("rti_role", ""),
                "email": metadata.get("email", ""),
                "designation": metadata.get("designation", ""),
                "office_name": metadata.get("office_name", ""),
                "office_code": metadata.get("office_code", ""),
                "department_name": metadata.get("department_name", ""),
                "district_name": (
                    metadata.get("district_name", "")
                    or metadata.get("district", "")
                ),
                "office_address": metadata.get("office_address", ""),
            }
        )

    return formatted_results


def _as_bool(value: object) -> bool:
    """Safely read boolean values sent by the frontend."""
    if isinstance(value, bool):
        return value

    return str(value or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


PIO_REPLY_INTENT_PATTERNS = (
    re.compile(
        r"\b(?:give|provide|need|want|show)\b"
        r".{0,50}\b(?:pio|public information officer)\b"
        r".{0,50}\b(?:reply|response|answer|advisory)\b",
        re.IGNORECASE | re.DOTALL,
     ),
    re.compile(
        r"\b(?:pio|public information officer)\b"
        r".{0,50}\b(?:reply|response|answer|advisory)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:draft|prepare|generate|write|create|make)\b"
        r".{0,90}\b(?:reply|response|pio|rti|application)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:reply|response|draft|pio advisory|pio analysis)\b"
        r".{0,90}\b(?:rti|pio|application)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:analyse|analyze|assess|review)\b"
        r".{0,90}\b(?:rti|application)\b"
        r".{0,90}\b(?:pio|reply|response|answer)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"(?:आर\s*\.?\s*टी\s*\.?\s*आई|आरटीआई|rti)"
        r".{0,90}(?:जवाब|उत्तर|प्रत्युत्तर|मसौदा|ड्राफ्ट|प्रतिक्रिया|विश्लेषण)",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"(?:जवाब|उत्तर|प्रत्युत्तर|मसौदा|ड्राफ्ट|प्रतिक्रिया|विश्लेषण)"
        r".{0,90}(?:आर\s*\.?\s*टी\s*\.?\s*आई|आरटीआई|rti|आवेदन|pio|पी\s*\.?\s*आई\s*\.?\s*ओ)",
        re.IGNORECASE | re.DOTALL,
    ),
)

RTI_DOCUMENT_MARKERS = (
    re.compile(
        r"(?im)^\s*(?:to|from|subject|application\s*(?:id|no|number))\b"
    ),
    re.compile(
        r"(?im)^\s*(?:सेवा\s+में|विषय|आवेदन\s*(?:क्रमांक|संख्या|आईडी)|प्रेषक)"
    ),
    re.compile(
        r"\b(?:rti\s+application|information\s+(?:sought|requested)|"
        r"certified\s+cop(?:y|ies)|public\s+authority|"
        r"application\s*(?:id|no|number)|cpio|spio)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:आरटीआई\s*आवेदन|सूचना\s*(?:प्रदान|उपलब्ध)|"
        r"प्रमाणित\s*प्रतिलिपि|कृपया\s*(?:उपलब्ध|प्रदान)|"
        r"आवेदन\s*(?:क्रमांक|संख्या|आईडी)|लोक\s*प्राधिकरण)"
    ),
)

RTI_BODY_LABEL = re.compile(
    r"(?is)"
    r"(?:"
    r"\b(?:rti(?:\s+(?:application|text))?|application\s+text)\b"
    r"|आरटीआई(?:\s*(?:आवेदन|पाठ))?"
    r")"
    r"\s*[:\-]\s*(?P<body>.+)$"
)


def _is_pio_advisory_request(query_text: str) -> bool:
    """Return True only for explicit RTI-reply/advisory requests."""
    text = str(query_text or "").strip()

    if not text:
        return False

    return any(pattern.search(text) for pattern in PIO_REPLY_INTENT_PATTERNS)


def _extract_rti_application_text(query_text: str) -> str:
    """
    Remove a user instruction when the RTI body is clearly labelled.

    Example:
    Prepare a PIO reply.

    RTI Application:
    <application text>
    """
    text = str(query_text or "").strip()

    label_match = RTI_BODY_LABEL.search(text)
    if label_match:
        body = label_match.group("body").strip()
        if body:
            return body

    lines = text.splitlines()

    if len(lines) >= 2 and _is_pio_advisory_request(lines[0]):
        remaining = "\n".join(lines[1:]).strip()
        if remaining:
            return remaining

    return text


def _looks_like_rti_application_text(rti_text: str) -> bool:
    """
    Avoid expensive PIO calls for short requests such as:
    'Prepare a reply for this RTI.'
    """
    text = str(rti_text or "").strip()

    if len(text) < 120:
        return False

    marker_count = sum(
        1
        for marker in RTI_DOCUMENT_MARKERS
        if marker.search(text)
    )

    if marker_count >= 2:
        return True

    return marker_count >= 1 and "\n" in text and len(text) >= 180


def _pio_application_required_answer(query_text: str) -> str:
    if re.search(r"[\u0900-\u097F]", query_text or ""):
        return (
            "PIO सलाहकार विश्लेषण के लिए पूरा RTI आवेदन आवश्यक है।\n\n"
            "कृपया उसी संदेश में पूरा आवेदन चिपकाएँ और स्पष्ट रूप से लिखें "
            "कि PIO उत्तर/सलाहकार रिपोर्ट तैयार करनी है।\n\n"
            "उदाहरण:\n"
            "RTI Application:\n"
            "[पूरा RTI आवेदन]\n\n"
            "इस RTI के लिए PIO सलाहकार उत्तर तैयार करें।"
        )

    return (
        "The PIO advisory workflow requires the complete RTI application text.\n\n"
        "Paste the full application in the same message and explicitly request "
        "a PIO reply or advisory report.\n\n"
        "Example:\n"
        "RTI Application:\n"
        "[full RTI application]\n\n"
        "Prepare a PIO advisory response for this RTI."
    )

@app.route('/api/query', methods=['POST'])
def query():
    """
    Unified query endpoint.

    Route resolution:
    - POSTGRES: CG RTI Officer Registry
    - QDRANT: legal knowledge base
    - HYBRID: both independently
    - UNCLEAR: clarification response
    """
    query_start_time = time.time()

    data = request.get_json() or {}

    raw_query_text = str(data.get("query", ""))
    query_text = extract_current_user_question(raw_query_text)
    pio_mode = _as_bool(data.get("pio_mode", False))
    try:
        requested_limit = int(data.get("num_results", num_results))
    except (TypeError, ValueError):
        requested_limit = num_results

    requested_limit = max(1, min(10, requested_limit))

    if not query_text:
        return jsonify(
            {
                "success": False,
                "error": "Query cannot be empty",
                "query": "",
                "results": [],
            }
        ), 400
    pio_advisory_requested = (
        pio_mode and _is_pio_advisory_request(query_text)
    )

    if pio_advisory_requested:
        rti_application_text = _extract_rti_application_text(query_text)

        print(
            "\n[PIO Router] "
            f"pio_mode=True, advisory_intent=True, "
            f"input_chars={len(rti_application_text)}"
        )

        try:
            print("[PIO Router] Starting three-call PIO advisory workflow")
            pio_result = analyze_pio_application(
                rti_text=rti_application_text
            )

            elapsed = time.time() - query_start_time

            print(
                "[PIO Router] PIO advisory workflow completed in "
                f"{elapsed:.2f}s"
            )

            return jsonify(
                {
                    "success": True,
                    "query": query_text,
                    "answer": pio_result["pio_advisory_report"],
                    "results": [],
                    "result_count": 0,
                    "execution_time": f"{elapsed:.2f}s",
                    "route": "PIO_ADVISORY",
                    "pio_mode": True,
                    "pio_pipeline_used": True,
                    "needs_clarification": False,
                    "validation": pio_result["validation"],
                    "rti_extraction": pio_result["rti_extraction"],
                    "legal_analysis": pio_result["legal_analysis"],
                    "precedent_search_available": True,
                    "next_action": (
                        "Ask whether the PIO wants CIC and CG SIC "
                        "decision references."
                    ),
                }
            ), 200

        except PIOPipelineError as error:
            print(f"[PIO Router] PIO advisory error: {error}")

            return jsonify(
                {
                    "success": False,
                    "error": str(error),
                    "query": query_text,
                    "results": [],
                    "route": "PIO_ADVISORY",
                    "pio_mode": True,
                    "pio_pipeline_used": True,
                }
            ), 422

        except Exception as error:
            print(f"[PIO Router] Unexpected PIO advisory error: {error}")
            import traceback
            traceback.print_exc()

            return jsonify(
                {
                    "success": False,
                    "error": "PIO advisory analysis could not be completed.",
                    "query": query_text,
                    "results": [],
                    "route": "PIO_ADVISORY",
                    "pio_mode": True,
                    "pio_pipeline_used": True,
                }
            ), 500
    try:
        print("\n⏱️ [FLASK] Unified request start")
        print(f"[Web UI] Raw query: {raw_query_text}")
        print(f"[Web UI] Current user question: {query_text}")

        retrieval = retrieve_from_all_sources(
            query=query_text,
            retrieve_context_fn=_retrieve_context_for_unified,
            retrieve_pio_directory_fn=_retrieve_pio_directory_for_unified,
            limit=requested_limit,
        )

        answer_result = generate_unified_answer(
            query=query_text,
            result=retrieval,
            generate_answer_fn=generate_answer,
        )

        formatted_results = _format_unified_evidence_for_frontend(
            retrieval.combined_evidence
        )

        total_time = time.time() - query_start_time

        print(
            "[Web UI] Final route: "
            f"{retrieval.resolution.final.route.value}"
        )
        print(
            "⏱️ [FLASK] Unified pipeline completed in "
            f"{total_time:.2f}s\n"
        )

        response = {
            "success": True,
            "query": query_text,
            "answer": answer_result.answer,
            "results": formatted_results,
            "result_count": len(formatted_results),
            "execution_time": f"{total_time:.2f}s",

            # Additive fields: old frontend can ignore these safely.
            "route": retrieval.resolution.final.route.value,
            "router_a_route": retrieval.resolution.router_a.route.value,
            "used_llm_fallback": retrieval.resolution.used_llm_fallback,
            "used_llm_answer": answer_result.used_llm,
            "needs_clarification": answer_result.needs_clarification,
        }

        if retrieval.errors:
            response["warnings"] = retrieval.errors

        return jsonify(response), 200

    except Exception as error:
        print(f"[Web UI] Unified query error: {error}")

        import traceback
        traceback.print_exc()

        return jsonify(
            {
                "success": False,
                "error": f"Error processing query: {str(error)}",
                "query": query_text,
                "results": [],
            }
        ), 500
    

@app.route('/api/pio/analyze', methods=['POST'])
def pio_analyze():
    """
    PIO advisory workflow, kept separate from the normal /api/query chatbot route.

    Request body:
    {
      "rti_text": "Full RTI application text"
    }
    """
    request_started_at = time.time()
    data = request.get_json(silent=True) or {}

    # Accept aliases to make the endpoint easier to connect to an existing form.
    rti_text = str(
        data.get('rti_text')
        or data.get('application_text')
        or data.get('query')
        or ''
    ).strip()

    if not rti_text:
        return jsonify({
            'success': False,
            'error': 'rti_text is required.',
        }), 400

    try:
        print("\n[PIO] Advisory analysis started")
        result = analyze_pio_application(rti_text=rti_text)
        elapsed = time.time() - request_started_at
        print(f"[PIO] Advisory analysis completed in {elapsed:.2f}s")

        return jsonify({
            'success': True,
            'execution_time': f'{elapsed:.2f}s',
            'rti_extraction': result['rti_extraction'],
            'legal_analysis': result['legal_analysis'],
            'pio_advisory_report': result['pio_advisory_report'],
            'validation': result['validation'],
            'precedent_search_available': True,
            'next_action': (
                'Ask whether the PIO wants CIC and CG SIC decision references.'
            ),
        }), 200

    except PIOPipelineError as error:
        print(f"[PIO] Analysis validation/provider error: {error}")
        return jsonify({
            'success': False,
            'error': str(error),
        }), 422

    except Exception as error:
        print(f"[PIO] Unexpected analysis error: {error}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'PIO analysis could not be completed.',
        }), 500

@app.route('/api/document-structure', methods=['POST'])
def document_structure():
    """Return precomputed full-document extraction artifacts for a PDF."""
    data = request.get_json() or {}
    actual_pdf = data.get('actual_pdf', '').strip()

    if not actual_pdf:
        return jsonify({
            'success': False,
            'error': 'actual_pdf is required',
        }), 400

    paths = get_document_artifact_paths(actual_pdf)
    structured_md_path = paths['structured_md']
    structured_json_path = paths['structured_json']

    if not structured_md_path.exists():
        return jsonify({
            'success': False,
            'error': 'structured.md not found',
            'actual_pdf': Path(actual_pdf).name,
            'document_id': paths['doc_id'],
            'expected_path': str(structured_md_path),
        }), 404

    response = {
        'success': True,
        'actual_pdf': Path(actual_pdf).name,
        'document_id': paths['doc_id'],
        'structured_md_path': str(structured_md_path),
        'structured_md': structured_md_path.read_text(encoding='utf-8', errors='replace'),
        'structured_json_available': structured_json_path.exists(),
        'structured_json_path': str(structured_json_path) if structured_json_path.exists() else '',
        'structured_json': None,
    }

    if structured_json_path.exists():
        try:
            response['structured_json'] = json.loads(
                structured_json_path.read_text(encoding='utf-8', errors='replace')
            )
        except json.JSONDecodeError as e:
            response['structured_json_error'] = f'Invalid structured.json: {e}'

    return jsonify(response), 200


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

@app.route('/api/document-pdf/<filename>', methods=['GET'])
@app.route('/01_preprocessing/used_files/<filename>', methods=['GET'])
@app.route('/01_preprocessing/cic_pdfs_past_cases/<filename>', methods=['GET'])
def serve_pdf(filename):
    """Serve a PDF from one of the approved local corpus directories."""
    if not filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Only PDF files are allowed'}), 403

    # Flask decodes the URL before this check, so reject path components after
    # decoding and only resolve a plain filename inside approved corpus roots.
    if Path(filename).name != filename or '..' in filename:
        return jsonify({'error': 'Invalid filename'}), 403

    pdf_roots = (
        PROJECT_ROOT / '01_preprocessing' / 'cic_pdfs_past_cases',
        PROJECT_ROOT / '01_preprocessing' / 'used_files',
    )
    pdf_path = next(
        (root / filename for root in pdf_roots if (root / filename).is_file()),
        None,
    )
    if pdf_path is None:
        return jsonify({
            'error': f'PDF not found: {filename}',
            'searched_folders': [root.name for root in pdf_roots],
        }), 404

    try:
        return send_file(str(pdf_path), mimetype='application/pdf')
    except Exception as e:
        print(f"[Web UI] Error serving PDF {filename}: {e}")
        return jsonify({'error': f'Error serving PDF: {str(e)}'}), 500

if __name__ == '__main__':
    print("\n" + "="*70)
    print("CHiPS-RAG Pipeline (Internal Backend)")
    print("="*70)
    print("\nRAG Pipeline Status: Deferred (loaded on demand)")
    print(f"Environment: {os.getenv('ENVIRONMENT', 'development')}")
    print("\nThis Flask server is INTERNAL ONLY.")
    print("Authentication is handled by Express.js at :3000")
    
    flask_host = os.getenv('FLASK_HOST', '0.0.0.0')
    flask_port = int(os.getenv('FLASK_PORT', '5000'))
    flask_debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    print(f"\nStarting Flask server on http://{flask_host}:{flask_port} (debug: {flask_debug})")
    print("Press Ctrl+C to stop the server\n")
    
    app.run(debug=flask_debug, host=flask_host, port=flask_port, use_reloader=False)
