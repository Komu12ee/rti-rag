'use strict';

const STORAGE_KEY = 'cg_rti_assistant_conversations_v1';
const ACTIVE_KEY = 'cg_rti_assistant_active_conversation_v1';
const MAX_CONTEXT_MESSAGES = 8;
const MAX_HISTORY_ITEMS = 24;

const ASSISTANT_SCOPE = [
  'You are the Chhattisgarh CG RTI portal assistant for citizens.',
  'Answer questions about how to use the CG RTI portal: registration, filing RTI, fee payment, first appeal, status tracking, and PIO or department contact details.',
  'Answer basic RTI Act questions: what RTI is, time limits, fees, first appeal process, and the basics of Sections 6, 7, 8, and 19.',
  'Answer questions about portal documents: manuals, FAQs, circulars, process charts, public notices, and PIO or department directories.',
  'If the question is outside this scope, briefly redirect the user to CG RTI portal help or RTI Act basics.'
].join(' ');

const DEFAULT_PROMPTS = [
  'How do I register on the CG RTI portal?',
  'How do I file an RTI application?',
  'How do I pay RTI fees?',
  'How do I file a first appeal?',
  'How can I check application status?',
  'How do I find PIO contact details?'
];

const $ = id => document.getElementById(id);

const ui = {
  newChat: $('new-chat'),
  clearChat: $('clear-chat'),
  historyList: $('history-list'),
  btnInit: $('btn-init'),
  btnSend: $('btn-send'),
  queryInput: $('query-input'),
  queryStatus: $('query-status'),
  queryTiming: $('query-timing'),
  chatPane: $('chat-pane'),
  chatInner: $('chat-inner'),
  footerTime: $('footer-time'),
  promptChips: $('prompt-chips'),
  botStatusPanel: $('bot-status-panel'),
  botStatusDot: $('bot-status-dot'),
  botStatusText: $('bot-status-text'),
  stPipelineDot: document.querySelector('#st-pipeline .status-dot'),
  stPipelineVal: $('st-pipeline-val'),
  stDbDot: document.querySelector('#st-db .status-dot'),
  stDbVal: $('st-db-val'),
  stDocsDot: document.querySelector('#st-docs .status-dot'),
  stDocsVal: $('st-docs-val'),
  drawerOverlay: $('drawer-overlay'),
  sourceDrawer: $('source-drawer'),
  drawerBody: $('drawer-body'),
  drawerClose: $('drawer-close'),
  pdfPanel: $('pdf-panel'),
  pdfOverlay: $('pdf-overlay'),
  pdfIframe: $('pdf-iframe'),
  pdfTitle: $('pdf-title'),
  pdfClose: $('pdf-close'),
  pdfLoading: $('pdf-loading'),
  documentLoadingLabel: $('document-loading-label'),
  documentError: $('document-error'),
  structureContent: $('structure-content'),
  toastContainer: $('toast-container')
};

const state = {
  initialized: false,
  loading: false,
  pdfBlobUrl: null,
  conversations: [],
  activeId: null
};

const api = {
  async request(method, path, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body !== undefined) opts.body = JSON.stringify(body);

    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  },
  health: () => api.request('GET', '/api/health'),
  init: () => api.request('POST', '/api/init'),
  dbStatus: () => api.request('GET', '/api/db-status'),
  query: (query, numResults) => api.request('POST', '/api/query', { query, num_results: numResults }),
  documentStructure: actualPdf => api.request('POST', '/api/document-structure', { actual_pdf: actualPdf }),
  async fetchPdf(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`PDF fetch failed: ${res.status}`);
    return res.blob();
  }
};

function nowIso() {
  return new Date().toISOString();
}

function newId() {
  return `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function truncate(value, max = 700) {
  const text = String(value ?? '').trim();
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

function loadConversations() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    state.conversations = Array.isArray(parsed) ? parsed : [];
  } catch (_) {
    state.conversations = [];
  }

  state.activeId = localStorage.getItem(ACTIVE_KEY);
  if (!state.conversations.some(c => c.id === state.activeId)) {
    const first = state.conversations[0] || createConversation(false);
    state.activeId = first.id;
  }
  saveConversations();
}

function saveConversations() {
  state.conversations.sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
  state.conversations = state.conversations.slice(0, MAX_HISTORY_ITEMS);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.conversations));
  localStorage.setItem(ACTIVE_KEY, state.activeId || '');
}

function createConversation(makeActive = true) {
  const conversation = {
    id: newId(),
    title: 'New chat',
    createdAt: nowIso(),
    updatedAt: nowIso(),
    messages: []
  };
  state.conversations.unshift(conversation);
  if (makeActive) state.activeId = conversation.id;
  return conversation;
}

function activeConversation() {
  let conversation = state.conversations.find(c => c.id === state.activeId);
  if (!conversation) conversation = createConversation(true);
  return conversation;
}

function titleFrom(text) {
  const clean = String(text || '').replace(/\s+/g, ' ').trim();
  return clean.length > 46 ? `${clean.slice(0, 46)}...` : clean || 'New chat';
}

function touchConversation(conversation) {
  conversation.updatedAt = nowIso();
  if (!conversation.title || conversation.title === 'New chat') {
    const firstUser = conversation.messages.find(m => m.role === 'user');
    if (firstUser) conversation.title = titleFrom(firstUser.display || firstUser.content);
  }
  saveConversations();
}

function renderHistory() {
  ui.historyList.innerHTML = '';

  if (!state.conversations.length) {
    const empty = document.createElement('div');
    empty.className = 'history-empty';
    empty.textContent = 'No history yet.';
    ui.historyList.appendChild(empty);
    return;
  }

  state.conversations.forEach(conversation => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = `history-item${conversation.id === state.activeId ? ' active' : ''}`;
    item.innerHTML = `
      <span class="history-title">${escapeHtml(conversation.title || 'New chat')}</span>
      <span class="history-date">${formatHistoryDate(conversation.updatedAt)}</span>
    `;
    item.addEventListener('click', () => {
      state.activeId = conversation.id;
      saveConversations();
      renderAll();
    });
    ui.historyList.appendChild(item);
  });
}

function formatHistoryDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function renderWelcome() {
  const wrap = document.createElement('div');
  wrap.className = 'welcome';
  wrap.id = 'welcome';
  wrap.innerHTML = `
    <h1>How can I help with RTI?</h1>
    <p>Ask about the CG RTI portal, filing steps, fees, appeals, application status, PIO contacts, RTI Act basics, or portal documents.</p>
    <div class="chips">
      ${DEFAULT_PROMPTS.map(prompt => `<button class="chip" type="button">${escapeHtml(prompt)}</button>`).join('')}
    </div>
  `;
  wrap.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => usePrompt(chip.textContent));
  });
  return wrap;
}

function renderMessages() {
  const conversation = activeConversation();
  ui.chatInner.innerHTML = '';

  if (!conversation.messages.length) {
    ui.chatInner.appendChild(renderWelcome());
    return;
  }

  conversation.messages.forEach(message => {
    ui.chatInner.appendChild(createMessageElement(message));
  });
  scrollChatToBottom();
}

function createMessageElement(message) {
  const wrapper = document.createElement('article');
  wrapper.className = `msg ${message.role === 'user' ? 'user' : 'bot'}${message.pending ? ' pending' : ''}`;

  const who = document.createElement('div');
  who.className = 'who';
  who.textContent = message.role === 'user' ? 'YOU' : 'AI';

  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  if (message.pending) {
    bubble.innerHTML = '<div class="dots"><span></span><span></span><span></span></div>';
  } else {
    const text = document.createElement('div');
    text.className = 'text';
    text.innerHTML = formatMessageText(message.display || message.content || '');
    bubble.appendChild(text);

    if (message.role === 'assistant' && message.timing) {
      const meta = document.createElement('div');
      meta.className = 'message-meta';
      meta.textContent = `Answered in ${message.timing}`;
      bubble.appendChild(meta);
    }

    if (message.role === 'assistant' && message.results?.length) {
      const btn = document.createElement('button');
      btn.className = 'sources-btn';
      btn.type = 'button';
      btn.innerHTML = `<span class="source-count">${message.results.length}</span> View sources`;
      btn.addEventListener('click', () => openDrawer(message.results));
      bubble.appendChild(btn);
    }
  }

  if (message.role === 'user') {
    wrapper.appendChild(bubble);
    wrapper.appendChild(who);
  } else {
    wrapper.appendChild(who);
    wrapper.appendChild(bubble);
  }

  return wrapper;
}

function formatMessageText(text) {
  const escaped = escapeHtml(text);
  return escaped
    .split(/\n{2,}/)
    .filter(Boolean)
    .map(part => `<p>${part.replace(/\n/g, '<br>')}</p>`)
    .join('');
}

function renderAll() {
  renderHistory();
  renderMessages();
}

function scrollChatToBottom() {
  requestAnimationFrame(() => {
    ui.chatPane.scrollTop = ui.chatPane.scrollHeight;
  });
}

function usePrompt(prompt) {
  ui.queryInput.value = prompt;
  autoResize();
  ui.queryInput.focus();
}

function autoResize() {
  ui.queryInput.style.height = 'auto';
  ui.queryInput.style.height = `${Math.min(ui.queryInput.scrollHeight, 160)}px`;
}

function setStatusRow(dot, val, stateValue, text) {
  dot.dataset.state = stateValue;
  val.textContent = text;
}

function setBotStatus(stateValue, text) {
  ui.botStatusPanel.dataset.state = stateValue;
  ui.botStatusDot.dataset.state = stateValue;
  ui.botStatusText.textContent = text;
}

function setAllStatus(ps, pt, ds, dt, qs, qt) {
  setStatusRow(ui.stPipelineDot, ui.stPipelineVal, ps, pt);
  setStatusRow(ui.stDbDot, ui.stDbVal, ds, dt);
  setStatusRow(ui.stDocsDot, ui.stDocsVal, qs, qt);

  const states = [ps, ds, qs];
  if (states.includes('loading')) {
    setBotStatus('loading', 'Checking bot status');
  } else if (states.includes('error')) {
    setBotStatus('error', 'Bot needs attention');
  } else if (states.every(state => state === 'ok')) {
    setBotStatus('ok', 'All systems operational');
  } else {
    setBotStatus('loading', 'Bot status pending');
  }
}

function updateFooterTime() {
  const now = new Date();
  ui.footerTime.textContent = now.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  });
}

function enableQueryBar(message = 'Ready') {
  ui.btnSend.disabled = false;
  ui.queryStatus.textContent = message;
}

function disableQueryBar(message = 'Loading...') {
  ui.btnSend.disabled = true;
  ui.queryStatus.textContent = message;
}

async function initPipeline() {
  ui.btnInit.disabled = true;
  ui.btnInit.textContent = 'Refreshing...';
  disableQueryBar('Refreshing bot...');
  setAllStatus('loading', 'checking', 'loading', 'checking', 'loading', 'checking');

  try {
    const { ok, data } = await api.init();
    if (ok && data.success) {
      state.initialized = true;
      toast('Bot refreshed successfully', 'success');
      await refreshDbStatus();
      enableQueryBar();
    } else {
      setAllStatus('error', 'failed', 'error', '-', 'error', '-');
      disableQueryBar('Refresh bot before asking');
      toast(data.error || 'Refresh failed', 'error', 5000);
    }
  } catch (err) {
    setAllStatus('error', 'offline', 'error', '-', 'error', '-');
    disableQueryBar('Backend unavailable');
    toast('Cannot reach backend', 'error');
  } finally {
    ui.btnInit.disabled = false;
    ui.btnInit.textContent = 'Refresh bot';
    updateFooterTime();
  }
}

async function refreshDbStatus() {
  try {
    const { ok, data } = await api.dbStatus();
    if (!ok) throw new Error(data.error || 'DB status failed');

    const dbReady = data.db_connected && data.collection_exists;
    const count = data.points_count ?? 0;
    setAllStatus(
      dbReady || state.initialized ? 'ok' : 'idle',
      dbReady || state.initialized ? 'ready' : '-',
      data.db_connected ? 'ok' : 'error',
      data.db_connected ? 'ready' : 'offline',
      data.db_connected ? 'ok' : 'idle',
      data.db_connected ? `${count.toLocaleString()} pts` : '-'
    );

    if (dbReady || state.initialized) enableQueryBar();
    else disableQueryBar('Refresh bot before asking');
  } catch (_) {
    setAllStatus('error', 'offline', 'error', '-', 'error', '-');
    disableQueryBar('Backend unavailable');
  }
  updateFooterTime();
}

async function bootStatus() {
  try {
    const { ok, data } = await api.health();
    if (ok && data.rag_pipeline === 'available') {
      state.initialized = Boolean(data.pipeline_initialized);
      await refreshDbStatus();
      if (state.initialized) enableQueryBar();
    } else {
      setAllStatus('error', 'unavailable', 'idle', '-', 'idle', '-');
      disableQueryBar('Assistant unavailable');
    }
  } catch (_) {
    setAllStatus('error', 'offline', 'error', '-', 'error', '-');
    disableQueryBar('Backend unavailable');
  }
}

function buildScopedQuery(userText) {
  const conversation = activeConversation();
  const recent = conversation.messages
    .filter(m => !m.pending)
    .slice(-MAX_CONTEXT_MESSAGES)
    .map(m => `${m.role === 'user' ? 'User' : 'Assistant'}: ${truncate(m.display || m.content, 700)}`)
    .join('\n');

  return [
    `Current user question: ${userText}`,
    recent ? `Recent conversation context:\n${recent}` : '',
    `Assistant role and answer scope:\n${ASSISTANT_SCOPE}`
  ].filter(Boolean).join('\n\n');
}

async function sendQuery() {
  const text = ui.queryInput.value.trim();
  if (!text || state.loading) return;

  const conversation = activeConversation();
  const userMessage = {
    id: newId(),
    role: 'user',
    content: text,
    display: text,
    createdAt: nowIso()
  };
  conversation.messages.push(userMessage);
  touchConversation(conversation);

  ui.queryInput.value = '';
  autoResize();
  ui.queryTiming.textContent = '';

  const pendingMessage = {
    id: newId(),
    role: 'assistant',
    content: '',
    pending: true,
    createdAt: nowIso()
  };
  conversation.messages.push(pendingMessage);
  state.loading = true;
  disableQueryBar('Retrieving...');
  renderAll();

  try {
    const scopedQuery = buildScopedQuery(text);
    const { ok, data } = await api.query(scopedQuery, 5);
    const index = conversation.messages.findIndex(m => m.id === pendingMessage.id);

    if (ok && data.success) {
      conversation.messages[index] = {
        id: pendingMessage.id,
        role: 'assistant',
        content: data.answer || '',
        display: data.answer || '',
        results: data.results || [],
        timing: data.execution_time || '',
        createdAt: nowIso()
      };
      ui.queryTiming.textContent = data.execution_time || '';
    } else {
      conversation.messages[index] = {
        id: pendingMessage.id,
        role: 'assistant',
        content: data.error || 'Query failed',
        display: `Unable to answer: ${data.error || 'Query failed'}`,
        createdAt: nowIso()
      };
      toast(data.error || 'Query failed', 'error');
    }
  } catch (err) {
    const index = conversation.messages.findIndex(m => m.id === pendingMessage.id);
    conversation.messages[index] = {
      id: pendingMessage.id,
      role: 'assistant',
      content: 'Network error - is the backend running?',
      display: 'Network error - is the backend running?',
      createdAt: nowIso()
    };
    toast('Network error', 'error');
  } finally {
    state.loading = false;
    enableQueryBar();
    touchConversation(conversation);
    renderAll();
    updateFooterTime();
  }
}

function legalChunkLabel(chunkType) {
  const labels = {
    INFORMATION_REQUESTED: 'Information Requested',
    COMMISSION_OBSERVATIONS: 'Commission Observation',
    COMMISSION_FINDINGS: 'Commission Finding',
    FINAL_ORDER: 'Final Order',
    PIO_LEARNING_SIGNAL: 'PIO Learning',
    PRECEDENT_SUMMARY: 'Precedent Summary',
    GROUNDS_FOR_APPEAL: 'Grounds for Appeal',
    HEARING_SUBMISSIONS: 'Hearing Submissions',
    CASE_METADATA: 'Case Metadata'
  };
  return labels[chunkType] || 'Relevant Passage';
}

function openDrawer(results) {
  ui.drawerBody.innerHTML = '';

  results.forEach(result => {
    const card = document.createElement('div');
    card.className = 'source-card';

    const score = typeof result.score === 'number' ? result.score.toFixed(3) : '-';
    const fname = result.actual_pdf || result.source || 'unknown';
    const chunkType = result.chunk_type || '';
    const passage = result.text || result.excerpt || '';
    const metaParts = [
      result.case_number ? `Case: ${escapeHtml(result.case_number)}` : '',
      result.public_authority ? `Authority: ${escapeHtml(result.public_authority)}` : '',
      result.hearing_date ? `Hearing: ${escapeHtml(result.hearing_date)}` : '',
      result.outcome ? `Outcome: ${escapeHtml(result.outcome)}` : ''
    ].filter(Boolean);

    card.innerHTML = `
      <div class="source-card-header">
        <span class="source-rank">#${escapeHtml(result.rank || '')}</span>
        <span class="source-filename">${escapeHtml(fname)}</span>
        <span class="source-score">${score}</span>
      </div>
      ${metaParts.length ? `<div class="source-meta">${metaParts.join(' | ')}</div>` : ''}
      <div class="source-label">${escapeHtml(legalChunkLabel(chunkType))}${chunkType ? ` <span>${escapeHtml(chunkType)}</span>` : ''}</div>
      <details class="source-passage" ${passage.length < 700 ? 'open' : ''}>
        <summary>${passage.length > 700 ? 'Expand passage' : 'Passage'}</summary>
        <div>${escapeHtml(passage)}</div>
      </details>
    `;

    const actionRow = document.createElement('div');
    actionRow.className = 'source-actions';

    const pdfBtn = document.createElement('button');
    pdfBtn.className = 'pdf-open-btn';
    pdfBtn.type = 'button';
    pdfBtn.textContent = 'View PDF';
    pdfBtn.addEventListener('click', () => openPdfPanel(fname));
    actionRow.appendChild(pdfBtn);

    const structureBtn = document.createElement('button');
    structureBtn.className = 'structure-open-btn';
    structureBtn.type = 'button';
    structureBtn.textContent = 'View structure';
    structureBtn.disabled = result.structured_md_available === false;
    structureBtn.title = structureBtn.disabled
      ? 'structured.md is not available for this document'
      : 'Open extracted Markdown';
    structureBtn.addEventListener('click', () => openStructurePanel(fname));
    actionRow.appendChild(structureBtn);

    card.appendChild(actionRow);
    ui.drawerBody.appendChild(card);
  });

  ui.drawerOverlay.classList.remove('hidden');
  ui.sourceDrawer.classList.remove('hidden');
}

function closeDrawer() {
  ui.drawerOverlay.classList.add('hidden');
  ui.sourceDrawer.classList.add('hidden');
}

async function openPdfPanel(fname) {
  ui.pdfTitle.textContent = fname;
  ui.pdfIframe.src = '';
  ui.structureContent.textContent = '';
  ui.structureContent.classList.add('hidden');
  ui.documentError.textContent = '';
  ui.documentError.classList.add('hidden');
  ui.documentLoadingLabel.textContent = 'Loading PDF';
  ui.pdfLoading.classList.remove('hidden');
  ui.pdfIframe.classList.add('hidden');
  ui.pdfPanel.classList.remove('hidden');
  ui.pdfOverlay.classList.remove('hidden');

  try {
    const blob = await api.fetchPdf(`/api/document-pdf/${encodeURIComponent(fname)}`);
    if (state.pdfBlobUrl) URL.revokeObjectURL(state.pdfBlobUrl);
    state.pdfBlobUrl = URL.createObjectURL(blob);
    ui.pdfIframe.src = state.pdfBlobUrl;
    ui.pdfIframe.onload = () => {
      ui.pdfLoading.classList.add('hidden');
      ui.pdfIframe.classList.remove('hidden');
    };
  } catch (err) {
    ui.pdfLoading.classList.add('hidden');
    ui.documentError.textContent = `Could not load PDF: ${err.message}`;
    ui.documentError.classList.remove('hidden');
    toast('Could not load PDF', 'error');
  }
}

async function openStructurePanel(fname) {
  ui.pdfTitle.textContent = `${fname} / structured.md`;
  ui.pdfIframe.src = '';
  ui.pdfIframe.classList.add('hidden');
  ui.structureContent.textContent = '';
  ui.structureContent.classList.add('hidden');
  ui.documentError.textContent = '';
  ui.documentError.classList.add('hidden');
  ui.documentLoadingLabel.textContent = 'Loading structure';
  ui.pdfLoading.classList.remove('hidden');
  ui.pdfPanel.classList.remove('hidden');
  ui.pdfOverlay.classList.remove('hidden');

  try {
    const { ok, data } = await api.documentStructure(fname);
    ui.pdfLoading.classList.add('hidden');
    if (!ok || !data.success) throw new Error(data.error || 'structured.md request failed');
    ui.structureContent.textContent = data.structured_md || '';
    ui.structureContent.classList.remove('hidden');
  } catch (err) {
    ui.pdfLoading.classList.add('hidden');
    ui.documentError.textContent = `Could not load structure: ${err.message}`;
    ui.documentError.classList.remove('hidden');
    toast('Could not load structure', 'error');
  }
}

function closePdfPanel() {
  ui.pdfPanel.classList.add('hidden');
  ui.pdfOverlay.classList.add('hidden');
  ui.pdfIframe.src = '';
  ui.structureContent.textContent = '';
  ui.structureContent.classList.add('hidden');
  ui.documentError.textContent = '';
  ui.documentError.classList.add('hidden');
  if (state.pdfBlobUrl) {
    URL.revokeObjectURL(state.pdfBlobUrl);
    state.pdfBlobUrl = null;
  }
}

function toast(message, type = 'info', duration = 3500) {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  ui.toastContainer.appendChild(el);
  setTimeout(() => el.remove(), duration);
}

function startNewChat() {
  createConversation(true);
  saveConversations();
  ui.queryInput.value = '';
  ui.queryTiming.textContent = '';
  autoResize();
  renderAll();
  ui.queryInput.focus();
}

function clearActiveChat() {
  const conversation = activeConversation();
  conversation.messages = [];
  conversation.title = 'New chat';
  touchConversation(conversation);
  ui.queryTiming.textContent = '';
  renderAll();
}

function setupEvents() {
  ui.newChat.addEventListener('click', startNewChat);
  ui.clearChat.addEventListener('click', clearActiveChat);
  ui.btnInit.addEventListener('click', initPipeline);
  ui.btnSend.addEventListener('click', sendQuery);
  ui.queryInput.addEventListener('input', autoResize);
  ui.queryInput.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (!ui.btnSend.disabled) sendQuery();
    }
  });

  ui.drawerClose.addEventListener('click', closeDrawer);
  ui.drawerOverlay.addEventListener('click', closeDrawer);
  ui.pdfClose.addEventListener('click', closePdfPanel);
  ui.pdfOverlay.addEventListener('click', closePdfPanel);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      closeDrawer();
      closePdfPanel();
    }
  });
}

function boot() {
  loadConversations();
  setupEvents();
  renderAll();
  initPipeline();
  updateFooterTime();
  setInterval(updateFooterTime, 1000);
}

boot();
