"""
RAG Pipeline Web UI
Simple Flask-based interface for document question-answering
"""
from dotenv import load_dotenv
from services.hybrid_retriever import retrieve_from_all_sources
from services.query_scope import extract_current_user_question
from services.unified_answer_service import generate_unified_answer
from services.unified_answer_service import (
    normalise_answer_language,
    with_answer_language_instruction,
)
from services.pio_pipeline import (
    PIOPipelineError,
    analyze_pio_application,
    analyze_pio_application_stream,
)
from services.pio_precedent_service import (
    PRECEDENT_COLLECTIONS,
    PIOPrecedentError,
    retrieve_pio_precedent_references,
    retrieve_pio_precedent_references_stream,
    stream_precedent_informed_advisory,
)
from services.pio_qdrant_retriever import retrieve_pio_directory_references
import os
import sys
import importlib.util
import json
import re
import subprocess
import time
from urllib.parse import urlsplit

import requests
from flask import Flask, Response, request, jsonify, send_file, stream_with_context
from datetime import datetime
from pathlib import Path
from threading import Lock
from uuid import uuid4
from werkzeug.utils import secure_filename

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
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv("PIO_PDF_UPLOAD_MAX_BYTES", str(25 * 1024 * 1024)))

PREPROCESSING_DIR = PROJECT_ROOT / '01_preprocessing'
SMART_EXTRACT_SCRIPT = PREPROCESSING_DIR / 'run_smart_extract.py'
PIO_PDF_UPLOAD_ROOT = Path(
    os.getenv(
        "PIO_PDF_UPLOAD_ROOT",
        str(SCRIPT_DIR / "uploads" / "pio_pdf_advisory"),
    )
)
PIO_PDF_PREPROCESS_TIMEOUT_SECONDS = int(
    os.getenv("PIO_PDF_PREPROCESS_TIMEOUT_SECONDS", "300")
)
SUPPORTED_OCR_MODELS = {"ollama", "sarvam"}
SARVAM_SDK_REQUIREMENT = "sarvamai>=0.1.28,<0.2.0"

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

# Short-lived, server-side context for the optional CIC/CGSIC precedent follow-up.
# The browser receives only the advisory_id and never sends trusted legal context back.
PIO_ADVISORY_TTL_SECONDS = max(60, int(os.getenv("PIO_ADVISORY_TTL_SECONDS", "3600")))
PIO_ADVISORY_CACHE_MAX_ITEMS = max(10, int(os.getenv("PIO_ADVISORY_CACHE_MAX_ITEMS", "100")))
pio_advisory_cache: dict[str, dict] = {}
pio_advisory_cache_lock = Lock()


def _purge_expired_pio_advisories() -> None:
    now = time.time()
    with pio_advisory_cache_lock:
        expired_ids = [
            advisory_id
            for advisory_id, item in pio_advisory_cache.items()
            if float(item.get("expires_at", 0) or 0) <= now
        ]
        for advisory_id in expired_ids:
            pio_advisory_cache.pop(advisory_id, None)

        overflow = len(pio_advisory_cache) - PIO_ADVISORY_CACHE_MAX_ITEMS
        if overflow > 0:
            oldest_ids = sorted(
                pio_advisory_cache,
                key=lambda key: float(pio_advisory_cache[key].get("created_at", 0) or 0),
            )[:overflow]
            for advisory_id in oldest_ids:
                pio_advisory_cache.pop(advisory_id, None)


def _store_pio_advisory(pio_result: dict) -> str:
    _purge_expired_pio_advisories()
    advisory_id = str(uuid4())
    now = time.time()

    with pio_advisory_cache_lock:
        pio_advisory_cache[advisory_id] = {
            "created_at": now,
            "expires_at": now + PIO_ADVISORY_TTL_SECONDS,
            "rti_extraction": pio_result["rti_extraction"],
            "legal_analysis": pio_result["legal_analysis"],
            "pio_advisory_report": pio_result["pio_advisory_report"],
            "validation": pio_result["validation"],
            "precedent_result": None,
            "precedent_in_progress": False,
            "precedent_advisory_result": None,
            "precedent_advisory_in_progress": False,
        }

    return advisory_id


def _get_pio_advisory(advisory_id: str) -> dict | None:
    _purge_expired_pio_advisories()
    key = str(advisory_id or "").strip()
    if not key:
        return None

    with pio_advisory_cache_lock:
        return pio_advisory_cache.get(key)


def _precedent_collection_status() -> tuple[list[str], list[str]]:
    """Return CIC/CGSIC availability without using unrelated collections."""
    rag_module = _load_rag_module()
    if rag_module is None:
        return [], list(PRECEDENT_COLLECTIONS)

    try:
        client = rag_module.ensure_qdrant_client()
        available = [
            collection
            for collection in PRECEDENT_COLLECTIONS
            if client.collection_exists(collection)
        ]
        missing = [
            collection
            for collection in PRECEDENT_COLLECTIONS
            if collection not in available
        ]
        return available, missing
    except Exception as error:
        print(f"[PIO Precedents] Collection availability check failed: {error}")
        return [], list(PRECEDENT_COLLECTIONS)


def _sse(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _sse_response(generator):
    return Response(
        stream_with_context(generator()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _safe_uploaded_pdf_name(filename: str, upload_id: str) -> str:
    safe_name = secure_filename(filename or "")
    if not safe_name:
        safe_name = f"{upload_id}.pdf"
    if not safe_name.lower().endswith(".pdf"):
        safe_name = f"{Path(safe_name).stem or upload_id}.pdf"
    return safe_name


def _assert_pdf_signature(pdf_path: Path) -> None:
    with pdf_path.open("rb") as handle:
        signature = handle.read(5)
    if signature != b"%PDF-":
        raise ValueError("Uploaded file is not a valid PDF.")


def _find_structured_markdown(output_root: Path, pdf_stem: str) -> Path:
    expected = output_root / pdf_stem / "structured.md"
    if expected.exists():
        return expected

    matches = sorted(output_root.rglob("structured.md"))
    if not matches:
        raise RuntimeError("PDF preprocessing completed but structured.md was not generated.")
    return matches[0]


def _configured_ocr_model() -> str:
    """Read and validate the upload OCR provider from the shared .env."""
    ocr_model = os.getenv("OCR_MODEL", "ollama").strip().lower()
    if ocr_model not in SUPPORTED_OCR_MODELS:
        raise RuntimeError(
            "Invalid OCR_MODEL. Use either 'ollama' or 'sarvam'."
        )
    return ocr_model


def _ollama_ocr_tags_url() -> str:
    configured_base_url = os.getenv("OLLAMA_BASE_URL", "").strip()
    if configured_base_url:
        base_url = configured_base_url
    else:
        host = os.getenv("OLLAMA_HOST", "localhost").strip() or "localhost"
        port = os.getenv("OLLAMA_PORT", "11434").strip() or "11434"
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        try:
            has_port = urlsplit(host).port is not None
        except ValueError as error:
            raise RuntimeError("OLLAMA_HOST contains an invalid port.") from error
        base_url = host if has_port else f"{host.rstrip('/')}:{port}"

    if not base_url.startswith(("http://", "https://")):
        base_url = f"http://{base_url}"
    return f"{base_url.rstrip('/')}/api/tags"


def _ocr_runtime_status() -> dict:
    """Report whether the configured OCR provider can start in this runtime."""
    try:
        ocr_model = _configured_ocr_model()
    except RuntimeError as error:
        return {
            "model": os.getenv("OCR_MODEL", "ollama").strip().lower(),
            "ready": False,
            "error": str(error),
        }

    status = {
        "model": ocr_model,
        "ready": True,
        "error": None,
    }
    if ocr_model == "ollama":
        model = (
            os.getenv("OLLAMA_OCR_MODEL", "").strip()
            or "qwen3-vl:4b-instruct"
        )
        try:
            response = requests.get(_ollama_ocr_tags_url(), timeout=2)
            response.raise_for_status()
            available_models = {
                str(item.get("name") or item.get("model") or "").strip()
                for item in response.json().get("models", [])
                if isinstance(item, dict)
            }
            if model not in available_models:
                status.update({
                    "ready": False,
                    "error": (
                        f"OCR_MODEL=ollama is selected, but vision model '{model}' "
                        f"is not installed. Run: ollama pull {model}"
                    ),
                })
        except (requests.RequestException, ValueError, TypeError, RuntimeError) as error:
            status.update({
                "ready": False,
                "error": (
                    "OCR_MODEL=ollama is selected, but the local Ollama service "
                    "is unavailable."
                ),
            })
            print(f"[OCR status] Ollama readiness check failed: {error}")
        return status

    if not os.getenv("SARVAM_API_KEY", "").strip():
        status.update({
            "ready": False,
            "error": (
                "OCR_MODEL=sarvam is selected, but SARVAM_API_KEY is missing "
                "or blank in the Web UI environment."
            ),
        })
        return status

    try:
        sarvam_module = importlib.import_module("sarvamai")
        if not hasattr(sarvam_module, "SarvamAI"):
            raise ImportError("sarvamai.SarvamAI is unavailable")
    except Exception as error:
        install_command = (
            f'"{sys.executable}" -m pip install "{SARVAM_SDK_REQUIREMENT}"'
        )
        status.update({
            "ready": False,
            "error": (
                "OCR_MODEL=sarvam needs the Sarvam Document Intelligence SDK "
                "in the web server Python environment. Install the project "
                "requirements in that environment."
            ),
        })
        print(
            f"[OCR status] Sarvam SDK import failed: {error}. "
            f"Install with: {install_command}"
        )

    return status


class PDFPreprocessingError(RuntimeError):
    """Raised when smart extraction fails with a concise client-safe message."""


class OCRProviderUnavailableError(PDFPreprocessingError):
    """Raised when an OCR-required page cannot start its selected provider."""


def _preprocessing_error_summary(completed: subprocess.CompletedProcess) -> str:
    """Extract the useful provider failure instead of returning every child log."""
    combined = "\n".join(
        part.strip()
        for part in (completed.stderr or "", completed.stdout or "")
        if part and part.strip()
    )
    if not combined:
        return "PDF preprocessing failed."

    lines = [line.strip() for line in combined.splitlines() if line.strip()]
    candidate = ""
    for marker in (
        "[ERROR] Smart extraction failed:",
        "OCR failed on page",
        "OCR_MODEL=",
    ):
        matches = [line for line in lines if marker in line]
        if matches:
            candidate = matches[-1]
            break
    if not candidate:
        candidate = lines[-1]

    marker = "[ERROR] Smart extraction failed:"
    if marker in candidate:
        candidate = candidate.split(marker, 1)[1].strip()
        candidate = re.sub(r"^.*?\.pdf:\s*", "", candidate, count=1)
    else:
        candidate = re.sub(
            r"^.*?\|\s*(?:ERROR|WARNING)\s*\|\s*",
            "",
            candidate,
            count=1,
        )

    duplicate_prefix = re.compile(
        r"^((?:sarvam|ollama) OCR failed on page \d+:\s*)\1",
        flags=re.IGNORECASE,
    )
    while duplicate_prefix.search(candidate):
        candidate = duplicate_prefix.sub(r"\1", candidate, count=1)

    return candidate[:1200] or "PDF preprocessing failed."


def _client_safe_preprocessing_error(summary: str) -> str:
    """Map child failures to useful messages without exposing server paths/logs."""
    page_match = re.search(
        r"(?:sarvam|ollama) OCR failed on page (\d+)",
        summary,
        flags=re.IGNORECASE,
    )
    page_suffix = f" on page {page_match.group(1)}" if page_match else ""

    if "Sarvam Document Intelligence SDK" in summary:
        return (
            f"Sarvam OCR cannot start{page_suffix}: its Document Intelligence "
            "SDK is not installed in the Flask Python environment. Install the "
            "project requirements and retry."
        )
    if "SARVAM_API_KEY is missing or blank" in summary:
        return (
            f"Sarvam OCR cannot start{page_suffix}: SARVAM_API_KEY is missing "
            "or blank in the Web UI environment."
        )
    if summary.lower().startswith("ollama ocr failed on page"):
        return (
            f"Local Ollama OCR could not process the document{page_suffix}. "
            "Check that Ollama is running and OLLAMA_OCR_MODEL is installed."
        )
    if summary.lower().startswith("sarvam ocr failed on page"):
        return (
            f"Sarvam OCR could not process the document{page_suffix}. "
            "Check the Sarvam credentials/service and retry."
        )
    return "PDF preprocessing failed. Check the server log for details."


def _run_uploaded_pdf_preprocessing(pdf_path: Path, output_root: Path) -> tuple[Path, subprocess.CompletedProcess]:
    if not SMART_EXTRACT_SCRIPT.exists():
        raise RuntimeError(f"Preprocessing script not found: {SMART_EXTRACT_SCRIPT}")

    output_root.mkdir(parents=True, exist_ok=True)
    ocr_model = _configured_ocr_model()
    command = [
        sys.executable,
        str(SMART_EXTRACT_SCRIPT),
        str(pdf_path),
        "--output",
        str(output_root),
        "--force",
        "--ocr-model",
        ocr_model,
    ]
    completed = subprocess.run(
        command,
        cwd=str(PREPROCESSING_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=PIO_PDF_PREPROCESS_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        details = "\n".join(
            part.strip()
            for part in (completed.stderr or "", completed.stdout or "")
            if part and part.strip()
        )
        if details:
            print(f"[PIO PDF Upload] Full preprocessing failure log:\n{details}")
        raw_summary = _preprocessing_error_summary(completed)
        summary = _client_safe_preprocessing_error(raw_summary)
        provider_unavailable_markers = (
            "requires the Sarvam Document Intelligence SDK",
            "needs the Sarvam Document Intelligence SDK",
            "SARVAM_API_KEY is missing or blank",
        )
        is_provider_failure = bool(re.match(
            r"^(?:sarvam|ollama) OCR failed on page \d+:",
            raw_summary,
            flags=re.IGNORECASE,
        ))
        if (
            is_provider_failure
            or any(marker in raw_summary for marker in provider_unavailable_markers)
        ):
            raise OCRProviderUnavailableError(summary)
        raise PDFPreprocessingError(summary)

    return _find_structured_markdown(output_root, pdf_path.stem), completed


def _pio_json_response_from_result(
    *,
    pio_result: dict,
    query_label: str,
    answer_language: str,
    started_at: float,
    extra: dict | None = None,
) -> dict:
    advisory_id = _store_pio_advisory(pio_result)
    available_precedent_collections, missing_precedent_collections = (
        _precedent_collection_status()
    )
    payload = {
        "success": True,
        "query": query_label,
        "answer": pio_result["pio_advisory_report"],
        "results": [],
        "result_count": 0,
        "execution_time": f"{time.time() - started_at:.2f}s",
        "route": "PIO_ADVISORY",
        "pio_mode": True,
        "answer_language": answer_language,
        "pio_pipeline_used": True,
        "needs_clarification": False,
        "validation": pio_result["validation"],
        "rti_extraction": pio_result["rti_extraction"],
        "legal_analysis": pio_result["legal_analysis"],
        "advisory_id": advisory_id,
        "precedent_search_available": bool(available_precedent_collections),
        "precedent_collections_available": available_precedent_collections,
        "precedent_collections_missing": missing_precedent_collections,
        "precedent_search_completed": False,
        "next_action": "precedent_confirmation",
    }
    if extra:
        payload.update(extra)
    return payload


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
    ocr_status = _ocr_runtime_status()
    return jsonify({
        'status': 'ok' if ocr_status['ready'] else 'degraded',
        'rag_pipeline': 'available',
        'rag_module_loaded': _rag_module is not None,
        'pipeline_initialized': pipeline_initialized,
        'ocr_model': ocr_status['model'],
        'ocr_ready': ocr_status['ready'],
        'ocr_error': ocr_status['error'],
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
    query_text: str,
    num_context: int = 5,
    filters: dict | None = None,
):
    """
    Search only pio_directory_v1 after PostgreSQL returns zero rows.
    It reuses the existing rag_pipeline BGE-M3 model and Qdrant client.
    """
    rag_module = _load_rag_module()

    if rag_module is None:
        raise RuntimeError(
            _rag_import_error
            or "RAG pipeline is unavailable for PIO directory retrieval."
        )

    from services.pio_qdrant_runtime import retrieve_pio_directory_context

    return retrieve_pio_directory_context(
        query_text=query_text,
        num_context=num_context,
        filters=filters,
        rag_module=rag_module,
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


def _has_pio_advisory_material(advisory_text: str) -> bool:
    """
    Accept either a formal RTI application or a scenario-based PIO reply brief.

    The explicit advisory intent is checked separately. This gate only avoids
    running the PIO pipeline for empty/near-empty requests such as
    "prepare a reply" with no facts to analyse.
    """
    text = str(advisory_text or "").strip()
    if len(text) < 40:
        return False

    intent_words = re.compile(
        r"\b(?:prepare|draft|generate|write|create|make|pio|rti|reply|"
        r"response|advisory|application|for|this|the|a|an)\b",
        re.IGNORECASE,
    )
    remaining = intent_words.sub(" ", text)
    return bool(re.search(r"[A-Za-z\u0900-\u097F]{3,}", remaining))


def _pio_application_required_answer(
    query_text: str,
    answer_language: str = "en",
) -> str:
    if normalise_answer_language(answer_language) == "hi":
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
        "The PIO advisory workflow needs either the full RTI application text "
        "or a scenario with enough facts to analyse.\n\n"
        "Paste the application or describe what the applicant asked for, what "
        "records are available or unavailable, and what kind of PIO reply you "
        "want.\n\n"
        "Example:\n"
        "Scenario: The applicant asked for certified copies of payment "
        "records for 2022-23. The office has vouchers but no consolidated "
        "report. Prepare a PIO advisory response."
    )


@app.route('/api/query/stream', methods=['POST'])
def query_stream():
    """Streaming variant of /api/query using Server-Sent Events."""
    query_start_time = time.time()
    data = request.get_json() or {}

    raw_query_text = str(data.get("query", ""))
    query_text = extract_current_user_question(raw_query_text)
    pio_mode = _as_bool(data.get("pio_mode", False))
    answer_language = normalise_answer_language(data.get("answer_language", "en"))
    try:
        requested_limit = int(data.get("num_results", num_results))
    except (TypeError, ValueError):
        requested_limit = num_results
    requested_limit = max(1, min(10, requested_limit))

    def generate():
        answer_chunks: list[str] = []

        try:
            if not query_text:
                yield _sse("error", {"error": "Query cannot be empty", "query": ""})
                return

            if pio_mode and _is_pio_advisory_request(query_text):
                rti_application_text = _extract_rti_application_text(query_text)

                if not _has_pio_advisory_material(rti_application_text):
                    answer = _pio_application_required_answer(
                        query_text,
                        answer_language=answer_language,
                    )
                    yield _sse("token", {"text": answer})
                    yield _sse(
                        "done",
                        {
                            "success": True,
                            "query": query_text,
                            "answer": answer,
                            "results": [],
                            "result_count": 0,
                            "execution_time": f"{time.time() - query_start_time:.2f}s",
                            "route": "PIO_ADVISORY",
                            "pio_mode": True,
                            "answer_language": answer_language,
                            "pio_pipeline_used": True,
                            "needs_clarification": True,
                        },
                    )
                    return

                yield _sse(
                    "status",
                    {"message": "Analysing RTI application and legal provisions..."},
                )

                pio_result = None
                for event_type, payload in analyze_pio_application_stream(
                    rti_text=rti_application_text,
                    answer_language=answer_language,
                ):
                    if event_type == "token":
                        answer_chunks.append(str(payload))
                        yield _sse("token", {"text": str(payload)})
                    elif event_type == "result":
                        pio_result = payload

                if pio_result is None:
                    raise PIOPipelineError("PIO advisory stream finished without a result.")

                elapsed = time.time() - query_start_time
                advisory_id = _store_pio_advisory(pio_result)
                available_precedent_collections, missing_precedent_collections = (
                    _precedent_collection_status()
                )

                yield _sse(
                    "done",
                    {
                        "success": True,
                        "query": query_text,
                        "answer": pio_result["pio_advisory_report"],
                        "results": [],
                        "result_count": 0,
                        "execution_time": f"{elapsed:.2f}s",
                        "route": "PIO_ADVISORY",
                        "pio_mode": True,
                        "answer_language": answer_language,
                        "pio_pipeline_used": True,
                        "needs_clarification": False,
                        "validation": pio_result["validation"],
                        "rti_extraction": pio_result["rti_extraction"],
                        "legal_analysis": pio_result["legal_analysis"],
                        "advisory_id": advisory_id,
                        "precedent_search_available": bool(available_precedent_collections),
                        "precedent_collections_available": available_precedent_collections,
                        "precedent_collections_missing": missing_precedent_collections,
                        "precedent_search_completed": False,
                        "next_action": "precedent_confirmation",
                    },
                )
                return

            yield _sse("status", {"message": "Retrieving relevant context..."})
            retrieval = retrieve_from_all_sources(
                query=query_text,
                retrieve_context_fn=_retrieve_context_for_unified,
                retrieve_pio_directory_fn=_retrieve_pio_directory_for_unified,
                limit=requested_limit,
            )
            formatted_results = _format_unified_evidence_for_frontend(
                retrieval.combined_evidence
            )

            route_value = retrieval.resolution.final.route.value
            qdrant_result = retrieval.qdrant_result
            rag_module = _load_rag_module()
            generate_answer_stream_fn = (
                getattr(rag_module, "generate_answer_stream", None)
                if rag_module is not None
                else None
            )

            can_stream_legal = (
                route_value in {"QDRANT", "UNCLEAR"}
                and qdrant_result is not None
                and bool(qdrant_result.context_results)
                and callable(generate_answer_stream_fn)
            )

            if can_stream_legal:
                yield _sse("status", {"message": "Generating answer..."})
                legal_query = with_answer_language_instruction(
                    qdrant_result.lookup_query or query_text,
                    answer_language,
                )
                for chunk in generate_answer_stream_fn(
                    legal_query,
                    qdrant_result.context_results,
                ):
                    text = str(chunk)
                    answer_chunks.append(text)
                    yield _sse("token", {"text": text})

                answer = "".join(answer_chunks).strip()
                clean_answer_fn = getattr(rag_module, "_clean_generated_answer", None)
                if callable(clean_answer_fn):
                    answer = clean_answer_fn(answer)
                used_llm_answer = True
                needs_clarification = False
            else:
                answer_result = generate_unified_answer(
                    query=query_text,
                    result=retrieval,
                    generate_answer_fn=generate_answer,
                    answer_language=answer_language,
                )
                answer = answer_result.answer
                used_llm_answer = answer_result.used_llm
                needs_clarification = answer_result.needs_clarification
                yield _sse("token", {"text": answer})

            total_time = time.time() - query_start_time
            response = {
                "success": True,
                "query": query_text,
                "answer": answer,
                "results": formatted_results,
                "result_count": len(formatted_results),
                "execution_time": f"{total_time:.2f}s",
                "route": route_value,
                "router_a_route": retrieval.resolution.router_a.route.value,
                "used_llm_fallback": retrieval.resolution.used_llm_fallback,
                "used_llm_answer": used_llm_answer,
                "needs_clarification": needs_clarification,
                "answer_language": answer_language,
            }

            if retrieval.errors:
                response["warnings"] = retrieval.errors

            yield _sse("done", response)

        except Exception as error:
            print(f"[Web UI] Streaming query error: {error}")
            import traceback
            traceback.print_exc()
            yield _sse(
                "error",
                {
                    "success": False,
                    "error": f"Error processing query: {str(error)}",
                    "query": query_text,
                },
            )

    return _sse_response(generate)


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
    answer_language = normalise_answer_language(data.get("answer_language", "en"))
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
                rti_text=rti_application_text,
                answer_language=answer_language,
            )

            elapsed = time.time() - query_start_time

            print(
                "[PIO Router] PIO advisory workflow completed in "
                f"{elapsed:.2f}s"
            )

            advisory_id = _store_pio_advisory(pio_result)
            available_precedent_collections, missing_precedent_collections = (
                _precedent_collection_status()
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
                    "answer_language": answer_language,
                    "pio_pipeline_used": True,
                    "needs_clarification": False,
                    "validation": pio_result["validation"],
                    "rti_extraction": pio_result["rti_extraction"],
                    "legal_analysis": pio_result["legal_analysis"],
                    "advisory_id": advisory_id,
                    "precedent_search_available": bool(available_precedent_collections),
                    "precedent_collections_available": available_precedent_collections,
                    "precedent_collections_missing": missing_precedent_collections,
                    "precedent_search_completed": False,
                    "next_action": "precedent_confirmation",
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
                    "answer_language": answer_language,
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
                    "answer_language": answer_language,
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
            answer_language=answer_language,
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
            "answer_language": answer_language,
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
    answer_language = normalise_answer_language(data.get("answer_language", "en"))

    if not rti_text:
        return jsonify({
            'success': False,
            'error': 'rti_text is required.',
        }), 400

    try:
        print("\n[PIO] Advisory analysis started")
        result = analyze_pio_application(
            rti_text=rti_text,
            answer_language=answer_language,
        )
        elapsed = time.time() - request_started_at
        print(f"[PIO] Advisory analysis completed in {elapsed:.2f}s")

        advisory_id = _store_pio_advisory(result)
        available_precedent_collections, missing_precedent_collections = (
            _precedent_collection_status()
        )

        return jsonify({
            'success': True,
            'execution_time': f'{elapsed:.2f}s',
            'answer_language': answer_language,
            'rti_extraction': result['rti_extraction'],
            'legal_analysis': result['legal_analysis'],
            'pio_advisory_report': result['pio_advisory_report'],
            'validation': result['validation'],
            'advisory_id': advisory_id,
            'precedent_search_available': bool(available_precedent_collections),
            'precedent_collections_available': available_precedent_collections,
            'precedent_collections_missing': missing_precedent_collections,
            'precedent_search_completed': False,
            'next_action': 'precedent_confirmation',
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


@app.route('/api/pio/upload-pdf', methods=['POST'])
def pio_upload_pdf():
    """Upload an RTI PDF, extract Markdown, and run the PIO advisory workflow."""
    request_started_at = time.time()
    uploaded = request.files.get("pdf") or request.files.get("file")
    answer_language = normalise_answer_language(
        request.form.get("answer_language", "en")
    )

    if uploaded is None or not uploaded.filename:
        return jsonify({
            "success": False,
            "error": "A PDF file is required.",
        }), 400

    if Path(uploaded.filename).suffix.lower() != ".pdf":
        return jsonify({
            "success": False,
            "error": "Only .pdf uploads are supported.",
        }), 400

    upload_id = uuid4().hex
    original_filename = Path(uploaded.filename).name
    safe_filename = _safe_uploaded_pdf_name(original_filename, upload_id)
    upload_dir = PIO_PDF_UPLOAD_ROOT / upload_id
    input_dir = upload_dir / "input"
    output_root = upload_dir / "stage2_output"
    input_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = input_dir / safe_filename

    try:
        uploaded.save(pdf_path)
        _assert_pdf_signature(pdf_path)

        ocr_model = _configured_ocr_model()
        print(
            f"\n[PIO PDF Upload] Preprocessing uploaded PDF: {original_filename} "
            f"(OCR provider: {ocr_model})"
        )
        structured_md_path, _ = _run_uploaded_pdf_preprocessing(
            pdf_path=pdf_path,
            output_root=output_root,
        )
        extracted_markdown = structured_md_path.read_text(encoding="utf-8").strip()
        if not extracted_markdown:
            return jsonify({
                "success": False,
                "error": "The uploaded PDF was processed, but no readable text was extracted.",
                "source_pdf": original_filename,
            }), 422

        print(
            "[PIO PDF Upload] Starting three-call PIO advisory workflow "
            f"from extracted Markdown ({len(extracted_markdown)} chars)"
        )
        pio_result = analyze_pio_application(
            rti_text=extracted_markdown,
            answer_language=answer_language,
        )
        print("[PIO PDF Upload] PIO advisory workflow completed")

        payload = _pio_json_response_from_result(
            pio_result=pio_result,
            query_label=f"Uploaded PDF: {original_filename}",
            answer_language=answer_language,
            started_at=request_started_at,
            extra={
                "source_pdf": original_filename,
                "upload_id": upload_id,
                "extracted_markdown_chars": len(extracted_markdown),
                "ocr_model": ocr_model,
            },
        )
        return jsonify(payload), 200

    except ValueError as error:
        return jsonify({
            "success": False,
            "error": str(error),
        }), 400

    except subprocess.TimeoutExpired:
        return jsonify({
            "success": False,
            "error": "PDF preprocessing timed out. Try a smaller PDF or increase PIO_PDF_PREPROCESS_TIMEOUT_SECONDS.",
        }), 504

    except OCRProviderUnavailableError as error:
        print(f"[PIO PDF Upload] OCR provider unavailable: {error}")
        return jsonify({
            "success": False,
            "error": str(error),
            "source_pdf": original_filename,
            "ocr_model": _configured_ocr_model(),
        }), 503

    except PDFPreprocessingError as error:
        print(f"[PIO PDF Upload] Preprocessing error: {error}")
        return jsonify({
            "success": False,
            "error": str(error),
            "source_pdf": original_filename,
            "ocr_model": _configured_ocr_model(),
        }), 422

    except PIOPipelineError as error:
        print(f"[PIO PDF Upload] PIO advisory error: {error}")
        return jsonify({
            "success": False,
            "error": str(error),
            "source_pdf": original_filename,
            "route": "PIO_ADVISORY",
            "pio_mode": True,
            "answer_language": answer_language,
            "pio_pipeline_used": True,
        }), 422

    except Exception as error:
        print(f"[PIO PDF Upload] Unexpected error: {error}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": f"PDF upload advisory could not be completed: {error}",
            "source_pdf": original_filename,
        }), 500


@app.route('/api/pio/precedents/stream', methods=['POST'])
def pio_precedents_stream():
    """Streaming variant of /api/pio/precedents."""
    request_started_at = time.time()
    data = request.get_json(silent=True) or {}
    advisory_id = str(data.get("advisory_id") or "").strip()

    try:
        requested_limit = int(data.get("num_results", 5))
    except (TypeError, ValueError):
        requested_limit = 5
    requested_limit = max(1, min(5, requested_limit))

    def generate():
        if not advisory_id:
            yield _sse("error", {"success": False, "error": "advisory_id is required."})
            return

        advisory = _get_pio_advisory(advisory_id)
        if advisory is None:
            yield _sse(
                "error",
                {
                    "success": False,
                    "error": "This PIO advisory has expired or is no longer available. Generate the advisory again and retry.",
                    "advisory_id": advisory_id,
                },
            )
            return

        with pio_advisory_cache_lock:
            cached_result = advisory.get("precedent_result")
            if cached_result is not None:
                cached_response = dict(cached_result)
                cached_response.update({
                    "success": True,
                    "advisory_id": advisory_id,
                    "cached": True,
                })
                yield _sse("token", {"text": cached_response.get("answer", "")})
                yield _sse("done", cached_response)
                return

            if advisory.get("precedent_in_progress"):
                yield _sse(
                    "error",
                    {
                        "success": False,
                        "error": "Precedent references are already being prepared for this advisory.",
                        "advisory_id": advisory_id,
                    },
                )
                return

            advisory["precedent_in_progress"] = True

        try:
            yield _sse("status", {"message": "Searching CIC/CGSIC decisions..."})
            rag_module = _load_rag_module()
            if rag_module is None:
                raise PIOPrecedentError(
                    _rag_import_error or "RAG pipeline is unavailable for precedent retrieval."
                )

            print("[PIO Precedents] Streaming CIC + CGSIC reference addendum")
            answer_chunks: list[str] = []
            precedent_result = None

            for event_type, payload in retrieve_pio_precedent_references_stream(
                rti_extraction=advisory["rti_extraction"],
                legal_analysis=advisory["legal_analysis"],
                rag_module=rag_module,
                num_results=requested_limit,
            ):
                if event_type == "token":
                    text = str(payload)
                    answer_chunks.append(text)
                    yield _sse("token", {"text": text})
                elif event_type == "result":
                    precedent_result = payload

            if precedent_result is None:
                raise PIOPrecedentError("Precedent stream finished without a result.")

            elapsed = time.time() - request_started_at
            response = {
                "success": True,
                "route": "PIO_PRECEDENTS",
                "advisory_id": advisory_id,
                "answer": precedent_result["answer"],
                "results": precedent_result["results"],
                "result_count": precedent_result["result_count"],
                "execution_time": f"{elapsed:.2f}s",
                "precedent_search_completed": True,
                "precedent_collections_used": precedent_result["available_collections"],
                "warnings": precedent_result.get("warnings", []),
                "cached": False,
            }

            with pio_advisory_cache_lock:
                current = pio_advisory_cache.get(advisory_id)
                if current is not None:
                    current["precedent_result"] = dict(response)

            yield _sse("done", response)

        except Exception as error:
            print(f"[PIO Precedents] Streaming error: {error}")
            import traceback
            traceback.print_exc()
            yield _sse(
                "error",
                {
                    "success": False,
                    "error": str(error),
                    "advisory_id": advisory_id,
                },
            )

        finally:
            with pio_advisory_cache_lock:
                current = pio_advisory_cache.get(advisory_id)
                if current is not None:
                    current["precedent_in_progress"] = False

    return _sse_response(generate)


@app.route('/api/pio/precedent-advisory/stream', methods=['POST'])
def pio_precedent_advisory_stream():
    """Generate a revised PIO advisory using cached CIC/CGSIC references."""
    request_started_at = time.time()
    data = request.get_json(silent=True) or {}
    advisory_id = str(data.get("advisory_id") or "").strip()

    def generate():
        if not advisory_id:
            yield _sse("error", {"success": False, "error": "advisory_id is required."})
            return

        advisory = _get_pio_advisory(advisory_id)
        if advisory is None:
            yield _sse(
                "error",
                {
                    "success": False,
                    "error": "This PIO advisory has expired or is no longer available. Generate the advisory again and retry.",
                    "advisory_id": advisory_id,
                },
            )
            return

        with pio_advisory_cache_lock:
            cached_result = advisory.get("precedent_advisory_result")
            if cached_result is not None:
                cached_response = dict(cached_result)
                cached_response.update({
                    "success": True,
                    "advisory_id": advisory_id,
                    "cached": True,
                })
                yield _sse("token", {"text": cached_response.get("answer", "")})
                yield _sse("done", cached_response)
                return

            precedent_result = advisory.get("precedent_result")
            if precedent_result is None:
                yield _sse(
                    "error",
                    {
                        "success": False,
                        "error": "Generate CIC/CGSIC references before creating the precedent-informed advisory.",
                        "advisory_id": advisory_id,
                    },
                )
                return

            if advisory.get("precedent_advisory_in_progress"):
                yield _sse(
                    "error",
                    {
                        "success": False,
                        "error": "A precedent-informed advisory is already being generated for this RTI.",
                        "advisory_id": advisory_id,
                    },
                )
                return

            advisory["precedent_advisory_in_progress"] = True

        try:
            yield _sse("status", {"message": "Generating precedent-informed advisory..."})
            print("[PIO Precedents] Streaming precedent-informed PIO advisory")

            chunks: list[str] = []
            for chunk in stream_precedent_informed_advisory(
                rti_extraction=advisory["rti_extraction"],
                legal_analysis=advisory["legal_analysis"],
                original_advisory=advisory.get("pio_advisory_report", ""),
                precedent_result=precedent_result,
            ):
                text = str(chunk)
                chunks.append(text)
                yield _sse("token", {"text": text})

            answer = "".join(chunks).strip()
            elapsed = time.time() - request_started_at
            response = {
                "success": True,
                "route": "PIO_PRECEDENT_INFORMED_ADVISORY",
                "advisory_id": advisory_id,
                "answer": answer,
                "results": precedent_result.get("results", []),
                "result_count": int(precedent_result.get("result_count", 0) or 0),
                "execution_time": f"{elapsed:.2f}s",
                "precedent_collections_used": precedent_result.get("precedent_collections_used")
                or precedent_result.get("available_collections", []),
                "cached": False,
            }

            with pio_advisory_cache_lock:
                current = pio_advisory_cache.get(advisory_id)
                if current is not None:
                    current["precedent_advisory_result"] = dict(response)

            yield _sse("done", response)

        except Exception as error:
            print(f"[PIO Precedents] Precedent-informed advisory error: {error}")
            import traceback
            traceback.print_exc()
            yield _sse(
                "error",
                {
                    "success": False,
                    "error": str(error),
                    "advisory_id": advisory_id,
                },
            )

        finally:
            with pio_advisory_cache_lock:
                current = pio_advisory_cache.get(advisory_id)
                if current is not None:
                    current["precedent_advisory_in_progress"] = False

    return _sse_response(generate)


@app.route('/api/pio/precedents', methods=['POST'])
def pio_precedents():
    """Add CIC/CGSIC references to a previously generated PIO advisory."""
    request_started_at = time.time()
    data = request.get_json(silent=True) or {}
    advisory_id = str(data.get("advisory_id") or "").strip()

    if not advisory_id:
        return jsonify({
            "success": False,
            "error": "advisory_id is required.",
        }), 400

    try:
        requested_limit = int(data.get("num_results", 5))
    except (TypeError, ValueError):
        requested_limit = 5
    requested_limit = max(1, min(5, requested_limit))

    advisory = _get_pio_advisory(advisory_id)
    if advisory is None:
        return jsonify({
            "success": False,
            "error": "This PIO advisory has expired or is no longer available. Generate the advisory again and retry.",
            "advisory_id": advisory_id,
        }), 410

    with pio_advisory_cache_lock:
        cached_result = advisory.get("precedent_result")
        if cached_result is not None:
            cached_response = dict(cached_result)
            cached_response.update({
                "success": True,
                "advisory_id": advisory_id,
                "cached": True,
            })
            return jsonify(cached_response), 200

        if advisory.get("precedent_in_progress"):
            return jsonify({
                "success": False,
                "error": "Precedent references are already being prepared for this advisory.",
                "advisory_id": advisory_id,
            }), 409

        advisory["precedent_in_progress"] = True

    try:
        rag_module = _load_rag_module()
        if rag_module is None:
            raise PIOPrecedentError(
                _rag_import_error or "RAG pipeline is unavailable for precedent retrieval."
            )

        print("[PIO Precedents] Searching CIC + CGSIC collections only")
        precedent_result = retrieve_pio_precedent_references(
            rti_extraction=advisory["rti_extraction"],
            legal_analysis=advisory["legal_analysis"],
            rag_module=rag_module,
            num_results=requested_limit,
        )
        elapsed = time.time() - request_started_at

        response = {
            "success": True,
            "route": "PIO_PRECEDENTS",
            "advisory_id": advisory_id,
            "answer": precedent_result["answer"],
            "results": precedent_result["results"],
            "result_count": precedent_result["result_count"],
            "execution_time": f"{elapsed:.2f}s",
            "precedent_search_completed": True,
            "precedent_collections_used": precedent_result["available_collections"],
            "warnings": precedent_result.get("warnings", []),
            "cached": False,
        }

        with pio_advisory_cache_lock:
            current = pio_advisory_cache.get(advisory_id)
            if current is not None:
                current["precedent_result"] = dict(response)

        return jsonify(response), 200

    except PIOPrecedentError as error:
        print(f"[PIO Precedents] Safe retrieval error: {error}")
        return jsonify({
            "success": False,
            "error": str(error),
            "advisory_id": advisory_id,
        }), 422

    except Exception as error:
        print(f"[PIO Precedents] Unexpected error: {error}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": "CIC/CGSIC precedent references could not be prepared.",
            "advisory_id": advisory_id,
        }), 500

    finally:
        with pio_advisory_cache_lock:
            current = pio_advisory_cache.get(advisory_id)
            if current is not None:
                current["precedent_in_progress"] = False


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
