// Configuration
const API_BASE = '/api';
const ENDPOINTS = {
    HEALTH: `${API_BASE}/health`,
    QUERY: `${API_BASE}/query`,
    SETTINGS: `${API_BASE}/settings`,
    EXAMPLES: `${API_BASE}/examples`,
    INIT: `${API_BASE}/init`,
    DB_STATUS: `${API_BASE}/db-status`
};

// PDF Viewer State
let pdfDoc = null;
let currentPage = 1;
let totalPages = 0;
let currentPdfFileName = null;
let currentChunkName = null;

// DOM Elements
const queryInput = document.getElementById('queryInput');
const submitBtn = document.getElementById('submitBtn');
const submitText = document.getElementById('submitText');
const loading = document.getElementById('loading');
const kgToggle = document.getElementById('kgToggle');
const numResults = document.getElementById('numResults');
const ragStatusDot = document.querySelector('#ragStatus .status-dot');
const ragStatusText = document.getElementById('rag-status-text');
const dbStatusDot = document.querySelector('#dbStatus .status-dot');
const dbStatusText = document.getElementById('db-status-text');
const initBtn = document.getElementById('initBtn');
const examplesContainer = document.getElementById('examplesContainer');
const answerContainer = document.getElementById('answerContainer');
const answerContent = document.getElementById('answerContent');
const resultsContainer = document.getElementById('resultsContainer');
const resultsList = document.getElementById('resultsList');
const resultCount = document.getElementById('resultCount');
const errorContainer = document.getElementById('errorContainer');
const errorMessage = document.getElementById('errorMessage');
const noResultsContainer = document.getElementById('noResultsContainer');
const emptyState = document.getElementById('emptyState');

// Status Container Elements
const thinkingContainer = document.getElementById('thinkingContainer');
const thinkingTime = document.getElementById('thinkingTime');

// PDF Modal Elements
const pdfModal = document.getElementById('pdfModal');
const pdfTitle = document.getElementById('pdfTitle');
const pdfChunkInfo = document.getElementById('pdfChunkInfo');
const closePdfBtn = document.getElementById('closePdfBtn');
const pdfCanvas = document.getElementById('pdfCanvas');
const prevPageBtn = document.getElementById('prevPageBtn');
const nextPageBtn = document.getElementById('nextPageBtn');
const pageInfo = document.getElementById('pageInfo');
const currentPageSpan = document.getElementById('currentPage');
const totalPagesSpan = document.getElementById('totalPages');

// Timing tracking
let startTime = null;
let timerInterval = null;

// State
let isLoading = false;
let examples = [];
let ragAvailable = false;
let dbConnected = false;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    checkHealth();
    checkDbStatus();
    loadExamples();
    setupEventListeners();
    setupInitButton();
});

// Event Listeners
function setupEventListeners() {
    submitBtn.addEventListener('click', handleQuery);
    queryInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && e.ctrlKey) {
            handleQuery();
        }
    });
    
    // PDF Modal Listeners
    closePdfBtn.addEventListener('click', closePdfModal);
    prevPageBtn.addEventListener('click', previousPage);
    nextPageBtn.addEventListener('click', nextPage);
    pdfModal.addEventListener('click', (e) => {
        if (e.target === pdfModal) closePdfModal();
    });
}

// Status Management Functions
function startThinking() {
    thinkingContainer.style.display = 'block';
    startTime = Date.now();
    
    // Update elapsed time every 100ms
    if (timerInterval) clearInterval(timerInterval);
    timerInterval = setInterval(() => {
        const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
        thinkingTime.textContent = elapsed + 's';
    }, 100);
}

function stopThinking() {
    if (timerInterval) clearInterval(timerInterval);
    thinkingContainer.style.display = 'none';
}

function setupInitButton() {
    if (initBtn) {
        initBtn.addEventListener('click', initializePipeline);
    }
}

// Check API Health
async function checkHealth() {
    try {
        const response = await fetch(ENDPOINTS.HEALTH);
        if (response.ok) {
            const data = await response.json();
            ragAvailable = data.rag_pipeline === 'available';
            setRagStatus(ragAvailable ? 'connected' : 'error',
                ragAvailable ? 'RAG Ready' : 'RAG Unavailable');
        } else {
            setRagStatus('error', 'Service Unavailable');
        }
    } catch (error) {
        setRagStatus('error', 'RAG Offline');
        console.error('Health check failed:', error);
    }
}

async function checkDbStatus() {
    try {
        const response = await fetch(ENDPOINTS.DB_STATUS);
        if (response.ok) {
            const data = await response.json();
            dbConnected = data.db_connected && data.collection_exists;

            if (dbConnected) {
                setDbStatus('connected', `DB Ready (${data.points_count} points)`);
                initBtn.style.display = 'none'; // Hide init btn if already connected
            } else {
                setDbStatus('error', 'DB Not Ready');
                initBtn.style.display = 'inline-block'; // Show init btn if not connected

                if (data.error) {
                    console.warn('[DB Status]', data.error);
                }
            }
        } else {
            setDbStatus('error', 'DB Check Failed');
            initBtn.style.display = 'inline-block';
        }
    } catch (error) {
        setDbStatus('error', 'DB Offline');
        initBtn.style.display = 'inline-block';
        console.error('DB status check failed:', error);
    }
}

async function initializePipeline() {
    if (!ragAvailable) {
        showError('RAG pipeline is not available');
        return;
    }

    initBtn.disabled = true;
    const originalText = initBtn.textContent;
    initBtn.textContent = '⟳ Initializing...';

    try {
        const response = await fetch(ENDPOINTS.INIT, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        const data = await response.json();

        if (data.success) {
            console.log('[Web UI] Pipeline initialized successfully', data.details);
            setDbStatus('connected', 'DB Ready - Pipeline Initialized');
            initBtn.style.display = 'none';
            // Refresh DB status
            await new Promise(r => setTimeout(r, 1000));
            checkDbStatus();
            showError('✓ RAG Pipeline initialized successfully!');
        } else {
            console.error('[Web UI] Initialization failed:', data);
            setDbStatus('error', 'Initialization Failed');
            showError(`Initialization failed: ${data.error}`);
        }
    } catch (error) {
        console.error('Initialization error:', error);
        setDbStatus('error', 'Initialization Error');
        showError(`Error initializing pipeline: ${error.message}`);
    } finally {
        initBtn.disabled = false;
        initBtn.textContent = originalText;
    }
}

function setRagStatus(state, text) {
    ragStatusDot.className = `status-dot ${state}`;
    ragStatusText.textContent = text;
}

function setDbStatus(state, text) {
    dbStatusDot.className = `status-dot ${state}`;
    dbStatusText.textContent = text;
}

// Load Examples
async function loadExamples() {
    try {
        const response = await fetch(ENDPOINTS.EXAMPLES);
        if (response.ok) {
            const data = await response.json();
            examples = data.examples || [];
            renderExamples();
        }
    } catch (error) {
        console.error('Failed to load examples:', error);
        examplesContainer.innerHTML = '<p style="grid-column: 1/-1; color: var(--text-secondary);">Could not load examples</p>';
    }
}

function renderExamples() {
    examplesContainer.innerHTML = '';
    examples.slice(0, 4).forEach(example => {
        const btn = document.createElement('button');
        btn.className = 'example-btn';
        btn.textContent = example;
        btn.addEventListener('click', () => {
            queryInput.value = example;
            queryInput.focus();
        });
        examplesContainer.appendChild(btn);
    });
}

// Handle Query
async function handleQuery() {
    const query = queryInput.value.trim();

    if (!query) {
        showError('Please enter a question');
        return;
    }

    if (isLoading) return;

    isLoading = true;
    submitBtn.disabled = true;
    submitText.style.display = 'none';
    loading.style.display = 'inline';

    // Hide previous results
    answerContainer.style.display = 'none';
    resultsContainer.style.display = 'none';
    errorContainer.style.display = 'none';
    noResultsContainer.style.display = 'none';
    emptyState.style.display = 'none';
    
    // Start thinking indicator
    startThinking();

    try {
        const payload = {
            query: query,
            use_kg: kgToggle.checked,
            num_results: parseInt(numResults.value)
        };

        const response = await fetch(ENDPOINTS.QUERY, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'Query failed');
        }

        const data = await response.json();

        if (data.success) {
            stopThinking();
            displayResults(data);
        } else {
            stopThinking();
            showError(data.error || 'Query processing failed');
        }
    } catch (error) {
        stopThinking();
        showError(error.message || 'An error occurred while processing your query');
        console.error('Query error:', error);
    } finally {
        isLoading = false;
        submitBtn.disabled = false;
        submitText.style.display = 'inline';
        loading.style.display = 'none';
    }
}

// Display Results
function displayResults(data) {
    // Display Answer
    if (data.answer) {
        answerContent.textContent = data.answer;
        answerContainer.style.display = 'block';
    }

    // Display Source Documents
    if (data.results && data.results.length > 0) {
        resultCount.textContent = `(${data.results.length})`;
        resultsList.innerHTML = '';

        data.results.forEach((result, index) => {
            const resultItem = createResultItem(result, index + 1);
            resultsList.appendChild(resultItem);
        });

        resultsContainer.style.display = 'block';
    } else {
        noResultsContainer.style.display = 'block';
    }
}

function createResultItem(result, rank) {
    const div = document.createElement('div');
    div.className = 'result-item';

    // Rank Badge
    const rankBadge = document.createElement('div');
    rankBadge.className = 'result-rank';
    rankBadge.textContent = rank;

    // Source - Show actual PDF name and chunk source
    const source = document.createElement('div');
    source.className = 'result-source';
    const actualPdf = result.actual_pdf || result.source || 'Unknown Source';
    const sourceText = result.actual_pdf ? 
        `📄 ${actualPdf}` : 
        result.source;
    source.innerHTML = `<strong>${sourceText}</strong>`;

    // Chunk Name Info
    const chunkInfo = document.createElement('div');
    chunkInfo.className = 'result-chunk-info';
    chunkInfo.textContent = `Chunk: ${result.source || 'N/A'}`;

    // View PDF Button
    const viewPdfBtn = document.createElement('button');
    viewPdfBtn.className = 'view-pdf-btn';
    viewPdfBtn.textContent = '📄 View PDF';
    viewPdfBtn.addEventListener('click', () => {
        openPdfViewer(result.actual_pdf, result.source);
    });

    // Scores
    const scoresDiv = document.createElement('div');
    scoresDiv.className = 'result-scores';

    const mainScoreBadge = document.createElement('div');
    mainScoreBadge.className = 'score-badge main';
    mainScoreBadge.innerHTML = `<span>Score</span><span>${(result.score * 100).toFixed(1)}%</span>`;
    scoresDiv.appendChild(mainScoreBadge);

    if (result.kg_score !== undefined) {
        const kgScoreBadge = document.createElement('div');
        kgScoreBadge.className = 'score-badge kg';
        kgScoreBadge.innerHTML = `<span>KG Score</span><span>${(result.kg_score * 100).toFixed(1)}%</span>`;
        scoresDiv.appendChild(kgScoreBadge);
    }

    // Text Preview - Show highlighted excerpt if available
    const text = document.createElement('div');
    text.className = 'result-text';
    const textContent = result.excerpt || result.text || '';
    const preview = textContent.substring(0, 300);
    text.innerHTML = `<em style="color: var(--text-secondary);">Relevant excerpt:</em><br/>${preview}${textContent.length > 300 ? '...' : ''}`;

    // Entities (if available)
    let entitiesDiv = null;
    if (result.entities && result.entities.length > 0) {
        entitiesDiv = document.createElement('div');
        entitiesDiv.className = 'result-entities';

        const label = document.createElement('div');
        label.className = 'entities-label';
        label.textContent = '📌 Entities:';
        entitiesDiv.appendChild(label);

        const entitiesList = document.createElement('div');
        entitiesList.className = 'entities-list';

        result.entities.forEach(entity => {
            const tag = document.createElement('span');
            tag.className = 'entity-tag highlight';
            tag.textContent = entity;
            entitiesList.appendChild(tag);
        });

        entitiesDiv.appendChild(entitiesList);
    }

    // Assemble
    div.appendChild(rankBadge);
    div.appendChild(source);
    div.appendChild(chunkInfo);
    div.appendChild(viewPdfBtn);
    div.appendChild(scoresDiv);
    div.appendChild(text);
    if (entitiesDiv) {
        div.appendChild(entitiesDiv);
    }

    return div;
}

// Error Handling
function showError(message) {
    errorMessage.textContent = message;
    errorContainer.style.display = 'block';
    emptyState.style.display = 'none';
}

// Keyboard Shortcuts
document.addEventListener('keydown', (e) => {
    // Ctrl/Cmd + K to focus on query input
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        queryInput.focus();
    }

    // F1 for help
    if (e.key === 'F1') {
        e.preventDefault();
        showHelp();
    }
});

function showHelp() {
    alert(
        'Keyboard Shortcuts:\n' +
        '• Ctrl+K (or Cmd+K): Focus on query input\n' +
        '• Ctrl+Enter: Submit query (when in input field)\n' +
        '• F1: Show this help\n\n' +
        'Tips:\n' +
        '• Enable Knowledge Graph for better entity-aware results\n' +
        '• Ask specific questions for better answers\n' +
        '• Use Ctrl+Enter to quickly submit queries'
    );
}

// Utility: Format Date
function formatDate(dateString) {
    try {
        return new Date(dateString).toLocaleDateString();
    } catch {
        return dateString;
    }
}

// PDF Viewer Functions
async function openPdfViewer(pdfFileName, chunkName) {
    if (!pdfFileName) {
        alert('PDF file not available');
        return;
    }

    currentPdfFileName = pdfFileName;
    currentChunkName = chunkName;
    currentPage = 1;

    pdfTitle.textContent = `📄 ${pdfFileName}`;
    pdfChunkInfo.textContent = `Source: ${chunkName}`;
    
    // Show modal
    pdfModal.style.display = 'block';
    document.body.style.overflow = 'hidden';

    try {
        // Load PDF from /01_preprocessing/used_files/ directory
        const pdfUrl = `/01_preprocessing/used_files/${pdfFileName}`;
        
        pdfDoc = await pdfjsLib.getDocument(pdfUrl).promise;
        totalPages = pdfDoc.numPages;
        totalPagesSpan.textContent = totalPages;
        
        // Render first page
        await renderPage(currentPage);
    } catch (error) {
        console.error('Error loading PDF:', error);
        pdfChunkInfo.textContent = `Error loading PDF: ${error.message}`;
        alert(`Failed to load PDF: ${error.message}`);
    }
}

async function renderPage(pageNum) {
    if (!pdfDoc) return;

    try {
        const page = await pdfDoc.getPage(pageNum);
        currentPageSpan.textContent = pageNum;

        // Set canvas size
        const viewport = page.getViewport({ scale: 1.5 });
        pdfCanvas.width = viewport.width;
        pdfCanvas.height = viewport.height;

        // Render page
        const renderContext = {
            canvasContext: pdfCanvas.getContext('2d'),
            viewport: viewport
        };

        await page.render(renderContext).promise;
    } catch (error) {
        console.error('Error rendering page:', error);
        alert(`Failed to render page: ${error.message}`);
    }
}

function nextPage() {
    if (currentPage < totalPages) {
        currentPage++;
        renderPage(currentPage);
    }
}

function previousPage() {
    if (currentPage > 1) {
        currentPage--;
        renderPage(currentPage);
    }
}

function closePdfModal() {
    pdfModal.style.display = 'none';
    document.body.style.overflow = 'auto';
    pdfDoc = null;
    currentPage = 1;
    totalPages = 0;
}

// Auto-refresh health check every 30 seconds
setInterval(checkHealth, 30000);
