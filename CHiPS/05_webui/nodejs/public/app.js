/**
 * CHiPS-RAG  –  Frontend application
 *
 * Handles login → token storage → RAG UI.
 * All /api/* requests include Authorization: Bearer <token>.
 * On any 401 response the app redirects back to the login screen.
 * PDFs are fetched as blobs using the auth token and shown in a half-screen panel.
 */

'use strict';

// ── Token storage (sessionStorage: cleared on tab/browser close) ──────────
const TOKEN_KEY = 'chips_rag_token';
const USER_KEY  = 'chips_rag_user';

const session = {
  save(token, user)  {
    sessionStorage.setItem(TOKEN_KEY, token);
    sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  token()  { return sessionStorage.getItem(TOKEN_KEY); },
  user()   { try { return JSON.parse(sessionStorage.getItem(USER_KEY)); } catch { return null; } },
  clear()  { sessionStorage.removeItem(TOKEN_KEY); sessionStorage.removeItem(USER_KEY); },
  exists() { return !!sessionStorage.getItem(TOKEN_KEY); },
};

// ── State ─────────────────────────────────────────────────────────────────
const state = {
  initialized:  false,
  loading:      false,
  lastResults:  [],
  pdfBlobUrl:   null,   // current blob URL so we can revoke it on close
};

// ── DOM refs ──────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

const ui = {
  // login
  loginScreen:     $('login-screen'),
  loginForm:       $('login-form'),
  loginUsername:   $('login-username'),
  loginPassword:   $('login-password'),
  loginError:      $('login-error'),
  loginSubmit:     $('login-submit'),
  loginBtnText:    $('login-btn-text'),
  loginBtnSpinner: $('login-btn-spinner'),

  // app shell
  appShell:    $('app-shell'),
  userDisplay: $('user-display'),
  btnLogout:   $('btn-logout'),

  // rag ui
  btnInit:      $('btn-init'),
  btnSend:      $('btn-send'),
  queryInput:   $('query-input'),
  queryStatus:  $('query-status'),
  queryTiming:  $('query-timing'),
  chatEmpty:    $('chat-empty'),
  chatMessages: $('chat-messages'),
  exampleList:  $('example-list'),
  footerTime:   $('footer-time'),

  stPipelineDot: document.querySelector('#st-pipeline .status-dot'),
  stPipelineVal: $('st-pipeline-val'),
  stDbDot:       document.querySelector('#st-db .status-dot'),
  stDbVal:       $('st-db-val'),
  stDocsDot:     document.querySelector('#st-docs .status-dot'),
  stDocsVal:     $('st-docs-val'),

  numResults:    $('num-results'),
  numResultsLbl: $('num-results-display'),
  kgToggle:      $('kg-toggle'),

  // source chunk drawer (right)
  drawerOverlay: $('drawer-overlay'),
  sourceDrawer:  $('source-drawer'),
  drawerBody:    $('drawer-body'),
  drawerClose:   $('drawer-close'),

  // pdf panel (left half)
  pdfPanel:      $('pdf-panel'),
  pdfOverlay:    $('pdf-overlay'),
  pdfIframe:     $('pdf-iframe'),
  pdfTitle:      $('pdf-title'),
  pdfClose:      $('pdf-close'),
  pdfLoading:    $('pdf-loading'),

  toastContainer: $('toast-container'),
};

// ── API client ────────────────────────────────────────────────────────────
const api = {
  async _request(method, path, body, requiresAuth = true) {
    const headers = { 'Content-Type': 'application/json' };
    if (requiresAuth) {
      const token = session.token();
      if (token) headers['Authorization'] = `Bearer ${token}`;
    }

    const opts = { method, headers };
    if (body !== undefined) opts.body = JSON.stringify(body);

    const res  = await fetch(path, opts);
    const json = await res.json().catch(() => ({}));

    if (res.status === 401) {
      session.clear();
      showLogin(json.expired
        ? 'Your session has expired. Please sign in again.'
        : 'Authentication required.');
      throw new Error('UNAUTHENTICATED');
    }

    return { ok: res.ok, status: res.status, data: json };
  },

  // Fetch a PDF as a blob (uses auth token, stays in same page)
  async fetchPdf(path) {
    const res = await fetch(path, {
      headers: { 'Authorization': `Bearer ${session.token()}` },
    });
    if (res.status === 401) {
      session.clear();
      showLogin('Your session has expired. Please sign in again.');
      throw new Error('UNAUTHENTICATED');
    }
    if (!res.ok) throw new Error(`PDF fetch failed: ${res.status}`);
    return res.blob();
  },

  login:    (username, password) =>
    api._request('POST', '/auth/login', { username, password }, false),
  logout:   () =>
    api._request('POST', '/auth/logout', undefined, false),
  health:   ()     => api._request('GET',  '/api/health'),
  init:     ()     => api._request('POST', '/api/init'),
  dbStatus: ()     => api._request('GET',  '/api/db-status'),
  examples: ()     => api._request('GET',  '/api/examples'),
  settings: (body) => api._request(body ? 'POST' : 'GET', '/api/settings', body),
  query:    (q, n) => api._request('POST', '/api/query', { query: q, num_results: n }),
};

// ── Screen switching ──────────────────────────────────────────────────────
function showLogin(errorMsg) {
  ui.appShell.classList.add('hidden');
  ui.loginScreen.classList.remove('hidden');
  ui.loginUsername.value = '';
  ui.loginPassword.value = '';
  if (errorMsg) showLoginError(errorMsg);
  else          hideLoginError();
  ui.loginUsername.focus();
}

function showApp() {
  ui.loginScreen.classList.add('hidden');
  ui.appShell.classList.remove('hidden');
  const user = session.user();
  if (user) ui.userDisplay.textContent = user.username;
}

function showLoginError(msg) {
  ui.loginError.textContent = msg;
  ui.loginError.classList.remove('hidden');
}
function hideLoginError() {
  ui.loginError.classList.add('hidden');
}

// ── Login form ────────────────────────────────────────────────────────────
async function handleLogin(e) {
  e.preventDefault();
  hideLoginError();

  const username = ui.loginUsername.value.trim();
  const password = ui.loginPassword.value;

  if (!username || !password) {
    showLoginError('Please enter both username and password.');
    return;
  }

  ui.loginSubmit.disabled = true;
  ui.loginBtnText.classList.add('hidden');
  ui.loginBtnSpinner.classList.remove('hidden');

  try {
    const { ok, data } = await api.login(username, password);
    if (ok && data.success) {
      session.save(data.token, data.user);
      showApp();
      bootRagUI();
    } else {
      showLoginError(data.error || 'Invalid credentials.');
    }
  } catch (err) {
    if (err.message !== 'UNAUTHENTICATED') {
      showLoginError('Cannot reach server. Please try again.');
    }
  }

  ui.loginSubmit.disabled = false;
  ui.loginBtnText.classList.remove('hidden');
  ui.loginBtnSpinner.classList.add('hidden');
}

// ── Logout ────────────────────────────────────────────────────────────────
async function handleLogout() {
  await api.logout().catch(() => {});
  session.clear();
  closePdfPanel();
  closeDrawer();
  showLogin();
  toast('Signed out.', 'info', 2000);
}

// ── Toast ─────────────────────────────────────────────────────────────────
function toast(message, type = 'info', duration = 3500) {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  ui.toastContainer.appendChild(el);
  setTimeout(() => el.remove(), duration);
}

// ── Status helpers ────────────────────────────────────────────────────────
function setStatusRow(dot, val, stateVal, text) {
  dot.dataset.state = stateVal;
  val.textContent   = text;
}
function setAllStatus(ps, pt, ds, dt, qs, qt) {
  setStatusRow(ui.stPipelineDot, ui.stPipelineVal, ps, pt);
  setStatusRow(ui.stDbDot,       ui.stDbVal,       ds, dt);
  setStatusRow(ui.stDocsDot,     ui.stDocsVal,     qs, qt);
}
function updateFooterTime() {
  const now = new Date();
  ui.footerTime.textContent =
    `Updated ${now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

// ── Init pipeline ─────────────────────────────────────────────────────────
async function initPipeline() {
  ui.btnInit.disabled = true;
  ui.btnInit.textContent = 'Initialising…';
  setAllStatus('loading','checking…','loading','checking…','loading','checking…');

  try {
    const { ok, data } = await api.init();
    if (ok && data.success) {
      state.initialized = true;
      toast('Pipeline initialised successfully', 'success');
      await refreshDbStatus();
      enableQueryBar();
    } else {
      setAllStatus('error','failed','error','—','error','—');
      toast(data.error || 'Initialisation failed', 'error', 5000);
      ui.btnInit.textContent = 'Retry Init';
      ui.btnInit.disabled = false;
    }
  } catch (err) {
    if (err.message !== 'UNAUTHENTICATED') {
      setAllStatus('error','unreachable','error','—','error','—');
      toast('Cannot reach backend', 'error');
      ui.btnInit.textContent = 'Retry Init';
      ui.btnInit.disabled = false;
    }
  }
  updateFooterTime();
}

async function refreshDbStatus() {
  try {
    const { ok, data } = await api.dbStatus();
    if (ok) {
      const pipeOk = data.db_connected && data.collection_exists;
      const count  = data.points_count ?? 0;
      setAllStatus(
        pipeOk ? 'ok' : 'error', pipeOk ? 'ready' : 'error',
        data.db_connected ? 'ok' : 'error', data.db_connected ? 'connected' : 'disconnected',
        data.db_connected ? 'ok' : 'idle',  data.db_connected ? `${count.toLocaleString()} pts` : '—',
      );
      ui.btnInit.textContent = pipeOk ? 'Re-initialise' : 'Retry Init';
      ui.btnInit.disabled = false;
    }
  } catch (_) {}
  updateFooterTime();
}

// ── Query bar ─────────────────────────────────────────────────────────────
function enableQueryBar() {
  ui.btnSend.disabled        = false;
  ui.queryStatus.textContent = 'Ready';
}
function disableQueryBar(msg = 'Loading…') {
  ui.btnSend.disabled        = true;
  ui.queryStatus.textContent = msg;
}
function autoResize() {
  ui.queryInput.style.height = 'auto';
  ui.queryInput.style.height = `${ui.queryInput.scrollHeight}px`;
}

// ── Chat ──────────────────────────────────────────────────────────────────
function hideChatEmpty() { ui.chatEmpty.style.display = 'none'; }

function escapeHtml(str) {
  return str
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function appendMessage(role, text, meta = {}) {
  hideChatEmpty();
  const msg     = document.createElement('div');
  msg.className = `msg${role === 'thinking' ? ' msg-thinking' : ''}`;

  const roleEl      = document.createElement('div');
  roleEl.className  = 'msg-role';
  const label       = role === 'user' ? 'YOU' : role === 'assistant' ? 'ASSISTANT' : 'THINKING';
  roleEl.innerHTML  =
    `<span class="msg-role-accent">◈</span> ${label}` +
    (meta.timing ? `<span class="timing-chip">${meta.timing}</span>` : '');
  msg.appendChild(roleEl);

  const body     = document.createElement('div');
  body.className = `msg-body ${role}-body`;

  if (role === 'thinking') {
    body.innerHTML =
      '<div class="thinking-dot"></div>' +
      '<div class="thinking-dot"></div>' +
      '<div class="thinking-dot"></div>';
  } else {
    body.innerHTML = escapeHtml(text)
      .split('\n\n').filter(Boolean)
      .map(p => `<p style="margin-bottom:.6em">${p.replace(/\n/g,'<br>')}</p>`)
      .join('');

    if (role === 'assistant' && meta.results?.length) {
      const btn     = document.createElement('button');
      btn.className = 'sources-btn';
      btn.innerHTML = `<span class="source-count">${meta.results.length}</span> View sources`;
      btn.addEventListener('click', () => openDrawer(meta.results));
      body.appendChild(btn);
    }
  }

  msg.appendChild(body);
  ui.chatMessages.appendChild(msg);
  msg.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return msg;
}

// ── Send query ────────────────────────────────────────────────────────────
async function sendQuery() {
  const text = ui.queryInput.value.trim();
  if (!text || state.loading) return;

  state.loading = true;
  disableQueryBar('Retrieving…');
  appendMessage('user', text);
  ui.queryInput.value = '';
  autoResize();

  const thinkingEl = appendMessage('thinking', '');

  try {
    const numCtx       = parseInt(ui.numResults.value, 10);
    const { ok, data } = await api.query(text, numCtx);
    thinkingEl.remove();

    if (ok && data.success) {
      state.lastResults = data.results || [];
      appendMessage('assistant', data.answer, {
        timing:  data.execution_time,
        results: state.lastResults,
      });
      ui.queryTiming.textContent = data.execution_time;
    } else {
      appendMessage('assistant', `⚠ ${data.error || 'Unknown error'}`);
      toast(data.error || 'Query failed', 'error');
    }
  } catch (err) {
    if (err.message !== 'UNAUTHENTICATED') {
      thinkingEl.remove();
      appendMessage('assistant', '⚠ Network error — is the backend running?');
      toast('Network error', 'error');
    }
  }

  state.loading = false;
  enableQueryBar();
  updateFooterTime();
}

// ── PDF panel ─────────────────────────────────────────────────────────────
async function openPdfPanel(fname) {
  // Show panel immediately with loading state
  ui.pdfTitle.textContent   = fname;
  ui.pdfIframe.src          = '';
  ui.pdfLoading.classList.remove('hidden');
  ui.pdfIframe.classList.add('hidden');
  ui.pdfPanel.classList.remove('hidden');
  ui.pdfOverlay.classList.remove('hidden');

  try {
    const pdfPath = `/01_preprocessing/used_files/${encodeURIComponent(fname)}`;
    const blob    = await api.fetchPdf(pdfPath);

    // Revoke previous blob URL to free memory
    if (state.pdfBlobUrl) {
      URL.revokeObjectURL(state.pdfBlobUrl);
    }

    state.pdfBlobUrl = URL.createObjectURL(blob);
    ui.pdfIframe.src = state.pdfBlobUrl;

    // Show iframe once loaded
    ui.pdfIframe.onload = () => {
      ui.pdfLoading.classList.add('hidden');
      ui.pdfIframe.classList.remove('hidden');
    };
  } catch (err) {
    if (err.message !== 'UNAUTHENTICATED') {
      ui.pdfLoading.classList.add('hidden');
      ui.pdfPanel.innerHTML +=
        `<div class="pdf-error">Could not load PDF: ${escapeHtml(err.message)}</div>`;
      toast('Could not load PDF', 'error');
    }
  }
}

function closePdfPanel() {
  ui.pdfPanel.classList.add('hidden');
  ui.pdfOverlay.classList.add('hidden');
  ui.pdfIframe.src = '';
  if (state.pdfBlobUrl) {
    URL.revokeObjectURL(state.pdfBlobUrl);
    state.pdfBlobUrl = null;
  }
}

// ── Source drawer (right panel) ───────────────────────────────────────────
function openDrawer(results) {
  ui.drawerBody.innerHTML = '';

  results.forEach(r => {
    const card     = document.createElement('div');
    card.className = 'source-card';
    const score    = typeof r.score === 'number' ? r.score.toFixed(3) : '—';
    const fname    = r.actual_pdf || r.source || 'unknown';

    card.innerHTML = `
      <div class="source-card-header">
        <span class="source-rank">#${r.rank}</span>
        <span class="source-filename">${escapeHtml(fname)}</span>
        <span class="source-score">${score}</span>
      </div>
      <div class="source-excerpt">${escapeHtml(r.excerpt || r.text?.slice(0,300) || '')}</div>
    `;

    // View PDF button — fetches with auth token, shows in half-screen panel
    const pdfBtn     = document.createElement('button');
    pdfBtn.className = 'pdf-open-btn';
    pdfBtn.innerHTML = '⬡ View PDF';
    pdfBtn.addEventListener('click', () => openPdfPanel(fname));
    card.appendChild(pdfBtn);

    ui.drawerBody.appendChild(card);
  });

  ui.drawerOverlay.classList.remove('hidden');
  ui.sourceDrawer.classList.remove('hidden');
}

function closeDrawer() {
  ui.drawerOverlay.classList.add('hidden');
  ui.sourceDrawer.classList.add('hidden');
}

// ── Examples ──────────────────────────────────────────────────────────────
async function loadExamples() {
  try {
    const { ok, data } = await api.examples();
    if (!ok) return;
    ui.exampleList.innerHTML = '';
    (data.examples || []).forEach(ex => {
      const li = document.createElement('li');
      li.textContent = ex;
      li.addEventListener('click', () => {
        ui.queryInput.value = ex;
        autoResize();
        ui.queryInput.focus();
      });
      ui.exampleList.appendChild(li);
    });
  } catch (_) {}
}

async function pushSettings() {
  await api.settings({
    kg_enabled:  ui.kgToggle.checked,
    num_results: parseInt(ui.numResults.value, 10),
  }).catch(() => {});
}

// ── RAG UI boot ───────────────────────────────────────────────────────────
async function bootRagUI() {
  setInterval(() => {
    const now = new Date();
    ui.footerTime.textContent =
      now.toLocaleTimeString([], { hour:'2-digit', minute:'2-digit', second:'2-digit' });
  }, 1000);

  loadExamples();

  try {
    const { ok, data } = await api.health();
    if (ok && data.pipeline_initialized) {
      state.initialized = true;
      await refreshDbStatus();
      enableQueryBar();
    } else {
      setAllStatus('idle','—','idle','—','idle','—');
    }
  } catch (_) {
    setAllStatus('error','unreachable','error','—','error','—');
  }

  ui.btnInit.addEventListener('click', initPipeline);
  ui.btnSend.addEventListener('click', sendQuery);

  ui.queryInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!ui.btnSend.disabled) sendQuery();
    }
  });
  ui.queryInput.addEventListener('input', autoResize);

  ui.numResults.addEventListener('input',  () => {
    ui.numResultsLbl.textContent = ui.numResults.value;
  });
  ui.numResults.addEventListener('change', pushSettings);
  ui.kgToggle.addEventListener('change',   pushSettings);

  // Drawer close
  ui.drawerClose.addEventListener('click',   closeDrawer);
  ui.drawerOverlay.addEventListener('click', closeDrawer);

  // PDF panel close
  ui.pdfClose.addEventListener('click',   closePdfPanel);
  ui.pdfOverlay.addEventListener('click', closePdfPanel);

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeDrawer(); closePdfPanel(); }
  });
}

// ── Entry point ───────────────────────────────────────────────────────────
function boot() {
  ui.btnLogout.addEventListener('click', handleLogout);
  ui.loginForm.addEventListener('submit', handleLogin);
  ui.loginPassword.addEventListener('keydown', e => {
    if (e.key === 'Enter') handleLogin(e);
  });

  if (session.exists()) {
    showApp();
    bootRagUI();
  } else {
    showLogin();
  }
}

boot();
