const AUTH_TOKEN_KEY = 'cg_rti_auth_token';
const AUTH_USER_KEY = 'cg_rti_auth_user';

const $ = id => document.getElementById(id);
const state = {
  user: null,
  config: null,
  dashboard: null,
  datasets: [],
  experiments: [],
  versions: [],
  selectedExperiment: null,
  pollTimer: null,
};

const METRIC_LABELS = {
  precision_at_5: 'Precision@5',
  recall_at_5: 'Recall@5',
  mrr: 'MRR',
  ndcg: 'nDCG',
  context_relevance: 'Context relevance',
  faithfulness: 'Faithfulness',
  citation_correctness: 'Citation correctness',
  answer_completeness: 'Answer completeness',
  hallucination_score: 'Hallucination risk',
  route_correctness: 'Route correctness',
  pass_rate: 'Pass rate',
  mean_latency_ms: 'Mean latency',
  p95_latency_ms: 'P95 latency',
  total_tokens: 'Tokens',
  total_cost_inr: 'Estimated cost',
};

function authToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY) || sessionStorage.getItem(AUTH_TOKEN_KEY) || '';
}

function clearAuth() {
  for (const storage of [localStorage, sessionStorage]) {
    storage.removeItem(AUTH_TOKEN_KEY);
    storage.removeItem(AUTH_USER_KEY);
  }
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function toNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function formatInteger(value) {
  return Math.round(toNumber(value)).toLocaleString('en-IN');
}

function formatPercent(value) {
  return `${(toNumber(value) * 100).toFixed(1)}%`;
}

function formatLatency(value) {
  const ms = toNumber(value);
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${Math.round(ms)} ms`;
}

function formatCost(value) {
  const amount = toNumber(value);
  return `₹${amount < .01 ? amount.toFixed(5) : amount.toFixed(2)}`;
}

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('en-IN', {
    dateStyle: 'medium', timeStyle: 'short',
  }).format(date);
}

function truncate(value, length = 180) {
  const text = String(value || '').trim();
  return text.length > length ? `${text.slice(0, length).trim()}…` : text;
}

function metricLabel(name) {
  if (METRIC_LABELS[name]) return METRIC_LABELS[name];
  const match = String(name).match(/^(precision|recall)_at_(\d+)$/);
  if (match) return `${match[1][0].toUpperCase()}${match[1].slice(1)}@${match[2]}`;
  return String(name).replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase());
}

function formatMetric(name, value) {
  if (name.includes('latency_ms')) return formatLatency(value);
  if (name === 'total_cost_inr') return formatCost(value);
  if (name === 'total_tokens' || name === 'case_count' || name === 'passed_cases') return formatInteger(value);
  return formatPercent(value);
}

function statusBadge(status) {
  const value = String(status || 'unknown');
  return `<span class="status-badge ${escapeHtml(value.toLowerCase())}">${escapeHtml(value)}</span>`;
}

function toast(message, type = '') {
  const node = document.createElement('div');
  node.className = `toast ${type}`.trim();
  node.textContent = message;
  $('toast-stack').appendChild(node);
  setTimeout(() => node.remove(), 4200);
}

function setGlobalMessage(message = '') {
  const node = $('global-message');
  node.textContent = message;
  node.classList.toggle('hidden', !message);
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = authToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(path, { ...options, headers });
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json')
    ? await response.json()
    : { success: response.ok, text: await response.text() };
  if (response.status === 401 || response.status === 403) {
    clearAuth();
    window.location.assign('/');
    throw new Error(data.error || 'Administrator access is required.');
  }
  if (!response.ok || data.success === false) {
    throw new Error(data.error || `Request failed (HTTP ${response.status}).`);
  }
  return data;
}

function setView(name) {
  document.querySelectorAll('[data-view-panel]').forEach(panel => {
    panel.classList.toggle('is-active', panel.dataset.viewPanel === name);
  });
  document.querySelectorAll('.nav-item').forEach(button => {
    button.classList.toggle('is-active', button.dataset.view === name);
  });
  const titles = {
    overview: 'System overview',
    datasets: 'Benchmark datasets',
    experiments: 'Evaluation experiments',
    review: 'Human evaluation',
    versions: 'Prompt & model versions',
    monitoring: 'Monitoring & integrations',
  };
  $('view-title').textContent = titles[name] || 'RAG evaluation';
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function metricCard(label, value, detail = '', tone = '') {
  return `<article class="metric-card ${escapeHtml(tone)}">
    <div class="metric-label">${escapeHtml(label)}</div>
    <div class="metric-value">${escapeHtml(value)}</div>
    <div class="metric-detail">${escapeHtml(detail)}</div>
  </article>`;
}

function latestCompletedExperiment() {
  return state.experiments.find(item => item.status === 'COMPLETED') || null;
}

function recallMetric(metrics = {}) {
  const key = Object.keys(metrics).find(name => name.startsWith('recall_at_'));
  return key ? [key, metrics[key]] : ['recall_at_5', 0];
}

function renderOverview() {
  const counts = state.dashboard?.counts || {};
  const latest = latestCompletedExperiment();
  const metrics = latest?.aggregate_metrics || {};
  const [recallName, recallValue] = recallMetric(metrics);
  $('metric-cards').innerHTML = [
    metricCard('Benchmark cases', formatInteger(counts.cases), `${formatInteger(counts.datasets)} datasets`),
    metricCard('Experiments', formatInteger(counts.experiments), `${formatInteger(counts.running)} currently running`, counts.running ? 'warn' : ''),
    metricCard(metricLabel(recallName), latest ? formatPercent(recallValue) : '—', latest ? latest.name : 'No completed run', latest && recallValue >= .8 ? 'good' : ''),
    metricCard('Open alerts', formatInteger(counts.open_alerts), `${formatInteger(counts.human_reviews)} human reviews`, counts.open_alerts ? 'bad' : 'good'),
  ].join('');

  const recent = state.dashboard?.recent_experiments || [];
  $('overview-experiments').innerHTML = recent.length ? experimentTable(recent, false) : empty('No experiments yet.');
  renderFailureClusters();
  renderAlerts('overview-alerts', state.dashboard?.alerts || []);
}

function renderFailureClusters() {
  const clusters = state.dashboard?.failure_clusters || {};
  const entries = Object.entries(clusters).sort((a, b) => b[1] - a[1]);
  const container = $('failure-clusters');
  if (!entries.length) {
    container.className = 'cluster-list empty-state';
    container.textContent = 'No evaluated cases yet.';
    return;
  }
  const maximum = Math.max(...entries.map(([, count]) => count), 1);
  container.className = 'cluster-list';
  container.innerHTML = entries.map(([name, count]) => `<div class="cluster-row">
    <strong>${escapeHtml(name.replaceAll('_', ' '))}</strong>
    <div class="cluster-track"><span style="width:${Math.max(4, count / maximum * 100)}%"></span></div>
    <em>${formatInteger(count)}</em>
  </div>`).join('');
}

function renderAlerts(targetId, alerts) {
  const container = $(targetId);
  if (!alerts.length) {
    container.className = 'alert-list empty-state';
    container.textContent = 'No regression or drift alerts.';
    return;
  }
  container.className = 'alert-list';
  container.innerHTML = alerts.map(alert => `<article class="alert-item ${alert.acknowledged ? 'is-acknowledged' : ''}">
    <span class="severity-badge ${escapeHtml(String(alert.severity).toLowerCase())}">${escapeHtml(alert.severity)}</span>
    <div class="alert-body">
      <strong>${escapeHtml(String(alert.alert_type || '').replaceAll('_', ' '))}</strong>
      <p>${escapeHtml(alert.message)}</p>
      <small>${escapeHtml(formatDate(alert.created_at))}${alert.metric_name ? ` · ${escapeHtml(alert.metric_name)}` : ''}</small>
    </div>
    ${alert.acknowledged ? '<span class="status-badge completed">Acknowledged</span>' : `<button class="row-button" data-ack-alert="${escapeHtml(alert.id)}" type="button">Acknowledge</button>`}
  </article>`).join('');
}

function empty(message) {
  return `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function renderDatasets() {
  $('dataset-total').textContent = formatInteger(state.datasets.length);
  const container = $('dataset-list');
  if (!state.datasets.length) {
    container.className = 'card-list empty-state';
    container.textContent = 'No datasets uploaded.';
    return;
  }
  container.className = 'card-list';
  container.innerHTML = state.datasets.map(dataset => `<article class="dataset-card">
    <div>
      <h3>${escapeHtml(dataset.name)}</h3>
      <p>${escapeHtml(dataset.description || 'No description supplied.')}</p>
      <small>${formatInteger(dataset.case_count)} cases · ${escapeHtml(formatDate(dataset.created_at))}</small>
    </div>
    <button class="row-button" data-delete-dataset="${escapeHtml(dataset.id)}" data-dataset-name="${escapeHtml(dataset.name)}" type="button">Delete</button>
  </article>`).join('');
  refreshExperimentSelects();
}

function aggregateCells(experiment) {
  const metrics = experiment.aggregate_metrics || {};
  const [, recall] = recallMetric(metrics);
  return `<td class="numeric">${experiment.status === 'COMPLETED' ? formatPercent(recall) : '—'}</td>
    <td class="numeric">${experiment.status === 'COMPLETED' ? formatPercent(metrics.faithfulness) : '—'}</td>
    <td class="numeric">${experiment.status === 'COMPLETED' ? formatLatency(metrics.mean_latency_ms) : '—'}</td>`;
}

function experimentTable(experiments, selectable = true) {
  return `<table>
    <thead><tr>${selectable ? '<th>Compare</th>' : ''}<th>Experiment</th><th>Status</th><th>Progress</th><th>Recall</th><th>Faithfulness</th><th>Latency</th><th>Actions</th></tr></thead>
    <tbody>${experiments.map(experiment => `<tr>
      ${selectable ? `<td><input type="checkbox" aria-label="Compare ${escapeHtml(experiment.name)}" data-compare-id="${escapeHtml(experiment.id)}" ${experiment.status !== 'COMPLETED' ? 'disabled' : ''}></td>` : ''}
      <td class="table-title">${escapeHtml(experiment.name)}<span class="table-subtitle">${escapeHtml(experiment.dataset_name || '')}</span></td>
      <td>${statusBadge(experiment.status)}</td>
      <td class="numeric">${formatInteger(experiment.completed_cases)}/${formatInteger(experiment.case_count)}</td>
      ${aggregateCells(experiment)}
      <td><div class="row-actions"><button class="row-button" data-open-experiment="${escapeHtml(experiment.id)}" type="button">Inspect</button></div></td>
    </tr>`).join('')}</tbody>
  </table>`;
}

function renderExperiments() {
  const container = $('experiment-list');
  if (!state.experiments.length) {
    container.className = 'table-wrap empty-state';
    container.textContent = 'No experiments yet.';
  } else {
    container.className = 'table-wrap';
    container.innerHTML = experimentTable(state.experiments, true);
  }
  refreshExperimentSelects();
  schedulePoll();
}

function refreshExperimentSelects() {
  const datasetSelect = $('experiment-dataset');
  const currentDataset = datasetSelect.value;
  datasetSelect.innerHTML = '<option value="">Choose dataset</option>' + state.datasets
    .map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)} (${formatInteger(item.case_count)})</option>`).join('');
  if (state.datasets.some(item => item.id === currentDataset)) datasetSelect.value = currentDataset;

  const completed = state.experiments.filter(item => item.status === 'COMPLETED');
  const baseline = $('experiment-baseline');
  const currentBaseline = baseline.value;
  baseline.innerHTML = '<option value="">No baseline</option>' + completed
    .map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  if (completed.some(item => item.id === currentBaseline)) baseline.value = currentBaseline;

  const review = $('review-experiment');
  const currentReview = review.value;
  review.innerHTML = '<option value="">Choose experiment</option>' + completed
    .map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  if (completed.some(item => item.id === currentReview)) review.value = currentReview;
}

function renderMetricSet(targetId, metrics = {}) {
  const preferred = [
    Object.keys(metrics).find(key => key.startsWith('recall_at_')),
    Object.keys(metrics).find(key => key.startsWith('precision_at_')),
    'mrr', 'ndcg', 'faithfulness', 'citation_correctness',
    'answer_completeness', 'pass_rate', 'mean_latency_ms', 'total_cost_inr',
  ].filter(Boolean);
  const names = [...new Set(preferred)].filter(name => metrics[name] !== undefined).slice(0, 12);
  $(targetId).innerHTML = names.length
    ? names.map(name => metricCard(metricLabel(name), formatMetric(name, metrics[name]))).join('')
    : metricCard('Status', 'No results', 'Metrics appear after cases complete');
}

function documentLabel(document, index) {
  return document.source || document.actual_pdf || document.document_id || document.office_code || document.email || `Evidence ${index + 1}`;
}

function renderResultCard(result, includeReview = false) {
  const metrics = result.metrics || {};
  const documents = Array.isArray(result.retrieved_documents) ? result.retrieved_documents : [];
  const metricNames = [
    Object.keys(metrics).find(key => key.startsWith('recall_at_')),
    Object.keys(metrics).find(key => key.startsWith('precision_at_')),
    'mrr', 'ndcg', 'context_relevance', 'faithfulness', 'citation_correctness',
    'answer_completeness', 'route_correctness', 'latency_ms',
  ].filter(name => name && metrics[name] !== undefined);
  const existingReview = result.human_review || {};
  const scoreSelect = (name, label) => `<label>${label}<select name="${name}" required>${[1, 2, 3, 4, 5].map(score => `<option value="${score}" ${Math.round(toNumber(existingReview[name])) === score ? 'selected' : ''}>${score}</option>`).join('')}</select></label>`;
  return `<article class="result-card">
    <header class="result-head">
      <div><h3>${escapeHtml(result.ordinal)}. ${escapeHtml(result.question)}</h3><small>${escapeHtml(result.route || 'NO ROUTE')} · ${formatLatency(result.latency_ms)} · ${formatCost(result.estimated_cost_inr)}</small></div>
      <span class="cluster-badge ${escapeHtml(result.failure_cluster || '')}">${escapeHtml(String(result.failure_cluster || 'unclassified').replaceAll('_', ' '))}</span>
    </header>
    <div class="result-content">
      <div class="answer-grid">
        <div class="answer-block"><h4>Expected answer</h4><p>${escapeHtml(result.expected_answer || 'No expected answer supplied.')}</p></div>
        <div class="answer-block"><h4>Actual answer</h4><p>${escapeHtml(result.actual_answer || 'No answer produced.')}</p></div>
      </div>
      <div class="mini-metrics">${metricNames.map(name => `<span class="mini-metric">${escapeHtml(metricLabel(name))} <strong>${escapeHtml(formatMetric(name, metrics[name]))}</strong></span>`).join('')}</div>
      ${documents.length ? `<details><summary>Retrieved evidence (${documents.length})</summary><ol class="evidence-list">${documents.map((document, index) => `<li><strong>${escapeHtml(documentLabel(document, index))}</strong>${document.score !== undefined ? ` · score ${escapeHtml(toNumber(document.score).toFixed(3))}` : ''}<br>${escapeHtml(truncate(document.text || document.content || '', 260))}</li>`).join('')}</ol></details>` : '<p class="form-note">No retrieved evidence.</p>'}
      ${result.error ? `<div class="error-box">${escapeHtml(result.error)}</div>` : ''}
      ${includeReview ? `<form class="review-form" data-review-result="${escapeHtml(result.id)}">
        ${scoreSelect('relevance', 'Relevance')}
        ${scoreSelect('faithfulness', 'Faithfulness')}
        ${scoreSelect('citation_correctness', 'Citation correctness')}
        ${scoreSelect('completeness', 'Completeness')}
        <label class="review-notes">Reviewer notes<textarea name="notes" rows="2" placeholder="Explain errors, missing evidence, or approval notes"></textarea></label>
        <button class="button primary" type="submit">Save human review</button>
      </form>` : ''}
    </div>
  </article>`;
}

async function openExperiment(id, switchView = true) {
  const data = await api(`/api/evaluation/experiments/${encodeURIComponent(id)}`);
  state.selectedExperiment = data.experiment;
  $('experiment-detail-panel').classList.remove('hidden');
  $('experiment-detail-title').textContent = data.experiment.name;
  renderMetricSet('experiment-detail-metrics', data.experiment.aggregate_metrics || {});
  const results = data.experiment.results || [];
  $('experiment-results').innerHTML = results.length
    ? results.map(result => renderResultCard(result)).join('')
    : empty(data.experiment.status === 'FAILED' ? data.experiment.error || 'Experiment failed.' : 'No case results yet.');
  if (switchView) {
    setView('experiments');
    $('experiment-detail-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function renderComparison(experiments) {
  const panel = $('comparison-panel');
  panel.classList.remove('hidden');
  const metricNames = [...new Set(experiments.flatMap(item => Object.keys(item.metrics || {})))]
    .filter(name => !['case_count', 'passed_cases', 'failure_clusters'].includes(name));
  const preferred = metricNames.sort((a, b) => {
    const order = ['recall', 'precision', 'mrr', 'ndcg', 'context', 'faith', 'citation', 'answer', 'pass', 'latency', 'token', 'cost'];
    const rank = name => { const index = order.findIndex(prefix => name.startsWith(prefix) || name.includes(prefix)); return index < 0 ? 99 : index; };
    return rank(a) - rank(b);
  });
  $('comparison-table').innerHTML = `<table><thead><tr><th>Metric</th>${experiments.map(item => `<th>${escapeHtml(item.name)}</th>`).join('')}</tr></thead>
    <tbody>
      <tr><td class="table-title">Configuration</td>${experiments.map(item => `<td>${escapeHtml(item.config?.chunking_strategy || '')} / ${escapeHtml(item.config?.retrieval_mode || '')}<span class="table-subtitle">${escapeHtml(item.config?.embedding_model || '')}</span></td>`).join('')}</tr>
      ${preferred.map(name => `<tr><td class="table-title">${escapeHtml(metricLabel(name))}</td>${experiments.map(item => `<td class="numeric">${item.metrics?.[name] === undefined ? '—' : escapeHtml(formatMetric(name, item.metrics[name]))}</td>`).join('')}</tr>`).join('')}
    </tbody></table>`;
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderReview() {
  const experiment = state.selectedExperiment;
  const target = $('review-list');
  if (!experiment || $('review-experiment').value !== experiment.id) {
    target.className = 'result-list empty-state';
    target.textContent = 'Choose an experiment to begin review.';
    return;
  }
  const results = experiment.results || [];
  target.className = results.length ? 'result-list' : 'result-list empty-state';
  target.innerHTML = results.length ? results.map(result => renderResultCard(result, true)).join('') : 'No results to review.';
}

function renderVersions() {
  const container = $('version-list');
  if (!state.versions.length) {
    container.className = 'table-wrap empty-state';
    container.textContent = 'No versions registered.';
    return;
  }
  container.className = 'table-wrap';
  container.innerHTML = `<table><thead><tr><th>Type</th><th>Name</th><th>Version</th><th>Configuration</th><th>Registered</th></tr></thead>
    <tbody>${state.versions.map(version => `<tr><td>${statusBadge(version.version_type)}</td><td class="table-title">${escapeHtml(version.name)}</td><td class="numeric">${escapeHtml(version.version)}</td><td><code>${escapeHtml(truncate(JSON.stringify(version.config || {}), 120))}</code></td><td>${escapeHtml(formatDate(version.created_at))}</td></tr>`).join('')}</tbody></table>`;
}

function renderMonitoring() {
  const counts = state.dashboard?.counts || {};
  const latest = latestCompletedExperiment();
  const metrics = latest?.aggregate_metrics || {};
  $('monitoring-cards').innerHTML = [
    metricCard('Running jobs', formatInteger(counts.running), 'Background evaluation workers', counts.running ? 'warn' : 'good'),
    metricCard('Human reviews', formatInteger(counts.human_reviews), 'Saved expert scorecards'),
    metricCard('P95 latency', latest ? formatLatency(metrics.p95_latency_ms) : '—', latest?.name || 'No completed run'),
    metricCard('Tracked cost', latest ? formatCost(metrics.total_cost_inr) : '—', latest ? `${formatInteger(metrics.total_tokens)} tokens in latest run` : 'No usage captured'),
  ].join('');
  const observability = state.config?.observability || {};
  const rows = [
    ['Prometheus', true, 'Protected scrape endpoint is active'],
    ['MLflow', observability.mlflow_configured, observability.mlflow_configured ? 'Tracking URI configured' : 'Set MLFLOW_TRACKING_URI'],
    ['Langfuse', observability.langfuse_configured, observability.langfuse_configured ? 'Credentials configured' : 'Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY'],
  ];
  $('integration-status').innerHTML = rows.map(([name, connected, detail]) => `<div class="integration-row"><div><strong>${escapeHtml(name)}</strong><small>${escapeHtml(detail)}</small></div><span class="integration-state ${connected ? 'connected' : ''}">${connected ? 'Ready' : 'Not configured'}</span></div>`).join('');
  renderAlerts('monitoring-alerts', state.dashboard?.alerts || []);
}

function populateConfig() {
  const config = state.config || {};
  $('experiment-chunking').innerHTML = (config.chunking_strategies || [])
    .map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value.replaceAll('_', ' '))}</option>`).join('');
  $('experiment-retrieval').innerHTML = (config.retrieval_modes || [])
    .map(value => `<option value="${escapeHtml(value)}" ${value === 'hybrid' ? 'selected' : ''}>${escapeHtml(value)}</option>`).join('');
  $('experiment-embedding').value = config.current_embedding_model || 'BAAI/bge-m3';
  $('experiment-reranker-model').value = config.current_reranker_model || 'BAAI/bge-reranker-v2-m3';
  $('experiment-judge-model').value = config.current_model || 'current';
  $('experiment-model').value = config.current_model || 'current';
  const collections = config.collections || [];
  $('experiment-collections').placeholder = collections.length ? `Available: ${collections.join(', ')}` : 'Empty uses configured defaults';
  $('system-model').textContent = config.current_model_label || config.current_model || 'Model unavailable';
  const system = document.querySelector('.sidebar-system');
  system.classList.remove('is-error');
  system.classList.add('is-ready');
  $('system-state').textContent = 'Evaluation database ready';
  if (config.qdrant_error) {
    setGlobalMessage(`Qdrant collection discovery is unavailable: ${config.qdrant_error}. PostgreSQL-only benchmarks can still run.`);
  } else {
    setGlobalMessage('');
  }
}

function renderAll() {
  renderOverview();
  renderDatasets();
  renderExperiments();
  renderVersions();
  renderMonitoring();
  if ($('review-experiment').value) renderReview();
}

async function loadAll({ quiet = false } = {}) {
  if (!quiet) $('refresh-all').disabled = true;
  try {
    const [config, dashboard, datasets, experiments, versions] = await Promise.all([
      api('/api/evaluation/config'),
      api('/api/evaluation/dashboard'),
      api('/api/evaluation/datasets'),
      api('/api/evaluation/experiments'),
      api('/api/evaluation/versions'),
    ]);
    state.config = config;
    state.dashboard = dashboard.dashboard;
    state.datasets = datasets.datasets || [];
    state.experiments = experiments.experiments || [];
    state.versions = versions.versions || [];
    populateConfig();
    renderAll();
  } catch (error) {
    document.querySelector('.sidebar-system')?.classList.add('is-error');
    $('system-state').textContent = 'Evaluation service error';
    setGlobalMessage(error.message || 'Unable to load evaluation data.');
    if (!quiet) toast(error.message || 'Refresh failed.', 'error');
  } finally {
    $('refresh-all').disabled = false;
  }
}

function schedulePoll() {
  if (state.pollTimer) clearTimeout(state.pollTimer);
  const hasActive = state.experiments.some(item => ['QUEUED', 'RUNNING'].includes(item.status));
  if (!hasActive) return;
  state.pollTimer = setTimeout(async () => {
    await loadAll({ quiet: true });
    if (state.selectedExperiment && ['QUEUED', 'RUNNING'].includes(state.selectedExperiment.status)) {
      await openExperiment(state.selectedExperiment.id, false).catch(() => {});
    }
  }, 3000);
}

async function handleDatasetUpload(event) {
  event.preventDefault();
  // Event.currentTarget is cleared after an awaited promise.
  const formElement = event.currentTarget;
  const file = $('dataset-file').files[0];
  if (!file) return toast('Choose a CSV or JSON benchmark.', 'error');
  const form = new FormData();
  form.append('name', $('dataset-name').value.trim());
  form.append('description', $('dataset-description').value.trim());
  form.append('file', file);
  const button = event.submitter;
  button.disabled = true;
  button.textContent = 'Uploading…';
  try {
    const data = await api('/api/evaluation/datasets/upload', { method: 'POST', body: form });
    formElement?.reset();
    document.querySelector('.file-drop').classList.remove('has-file');
    toast(`Uploaded ${data.dataset.case_count} benchmark cases.`, 'success');
    await loadAll({ quiet: true });
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    button.disabled = false;
    button.textContent = 'Upload benchmark';
  }
}

async function handleExperimentCreate(event) {
  event.preventDefault();
  const button = event.submitter;
  const payload = {
    name: $('experiment-name').value.trim(),
    dataset_id: $('experiment-dataset').value,
    baseline_experiment_id: $('experiment-baseline').value || null,
    config: {
      chunking_strategy: $('experiment-chunking').value,
      chunk_size: toNumber($('experiment-chunk-size').value, 512),
      chunk_overlap: toNumber($('experiment-chunk-overlap').value, 64),
      embedding_model: $('experiment-embedding').value.trim(),
      collection_names: $('experiment-collections').value.split(',').map(item => item.trim()).filter(Boolean),
      retrieval_mode: $('experiment-retrieval').value,
      hybrid_alpha: toNumber($('experiment-hybrid-alpha').value, .6),
      top_k: toNumber($('experiment-top-k').value, 5),
      candidate_k: toNumber($('experiment-candidate-k').value, 20),
      prompt_version: $('experiment-prompt').value.trim(),
      prompt_instruction: $('experiment-prompt-instruction').value.trim(),
      model_version: $('experiment-model').value.trim(),
      reranker_enabled: $('experiment-reranker').checked,
      use_kg: $('experiment-kg').checked,
      use_multi_query: $('experiment-multi-query').checked,
      judge_enabled: $('experiment-judge').checked,
      judge_model: $('experiment-judge-model').value.trim(),
      reranker_model: $('experiment-reranker-model').value.trim(),
    },
  };
  button.disabled = true;
  button.textContent = 'Queueing…';
  try {
    const data = await api('/api/evaluation/experiments', { method: 'POST', body: JSON.stringify(payload) });
    toast(`Experiment “${data.experiment.name}” was queued.`, 'success');
    $('experiment-name').value = '';
    await loadAll({ quiet: true });
    await openExperiment(data.experiment.id, false);
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    button.disabled = false;
    button.textContent = 'Queue experiment';
  }
}

async function compareSelected() {
  const ids = Array.from(document.querySelectorAll('[data-compare-id]:checked')).map(node => node.dataset.compareId);
  if (ids.length < 2) return toast('Select at least two completed experiments.', 'error');
  try {
    const data = await api('/api/evaluation/compare', { method: 'POST', body: JSON.stringify({ experiment_ids: ids }) });
    renderComparison(data.experiments || []);
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function exportSelectedExperiment() {
  const experiment = state.selectedExperiment;
  if (!experiment) return;
  try {
    const response = await fetch(`/api/evaluation/experiments/${encodeURIComponent(experiment.id)}/export.csv`, {
      headers: { Authorization: `Bearer ${authToken()}` },
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || 'CSV export failed.');
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `rag-evaluation-${experiment.id}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function handleReviewSubmit(form) {
  const button = form.querySelector('button[type="submit"]');
  const formData = new FormData(form);
  const payload = Object.fromEntries(formData.entries());
  for (const key of ['relevance', 'faithfulness', 'citation_correctness', 'completeness']) payload[key] = Number(payload[key]);
  button.disabled = true;
  try {
    await api(`/api/evaluation/results/${encodeURIComponent(form.dataset.reviewResult)}/review`, {
      method: 'POST', body: JSON.stringify(payload),
    });
    toast('Human review saved.', 'success');
    await openExperiment(state.selectedExperiment.id, false);
    renderReview();
    await loadAll({ quiet: true });
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    button.disabled = false;
  }
}

async function handleVersionCreate(event) {
  event.preventDefault();
  const formElement = event.currentTarget;
  let configuration = {};
  try {
    const value = $('version-config').value.trim();
    configuration = value ? JSON.parse(value) : {};
  } catch (_) {
    return toast('Configuration must be valid JSON.', 'error');
  }
  const button = event.submitter;
  button.disabled = true;
  try {
    await api('/api/evaluation/versions', {
      method: 'POST',
      body: JSON.stringify({
        version_type: $('version-type').value,
        name: $('version-name').value.trim(),
        version: $('version-value').value.trim(),
        config: configuration,
      }),
    });
    formElement?.reset();
    toast('Version registered.', 'success');
    await loadAll({ quiet: true });
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    button.disabled = false;
  }
}

async function handleClick(event) {
  const goView = event.target.closest('[data-go-view]');
  if (goView) return setView(goView.dataset.goView);

  const openButton = event.target.closest('[data-open-experiment]');
  if (openButton) {
    try { await openExperiment(openButton.dataset.openExperiment); }
    catch (error) { toast(error.message, 'error'); }
    return;
  }

  const deleteButton = event.target.closest('[data-delete-dataset]');
  if (deleteButton) {
    const confirmed = window.confirm(`Delete benchmark “${deleteButton.dataset.datasetName}” and all of its experiments?`);
    if (!confirmed) return;
    try {
      await api(`/api/evaluation/datasets/${encodeURIComponent(deleteButton.dataset.deleteDataset)}`, { method: 'DELETE' });
      toast('Benchmark dataset deleted.', 'success');
      state.selectedExperiment = null;
      $('experiment-detail-panel').classList.add('hidden');
      await loadAll({ quiet: true });
    } catch (error) { toast(error.message, 'error'); }
    return;
  }

  const acknowledge = event.target.closest('[data-ack-alert]');
  if (acknowledge) {
    try {
      await api(`/api/evaluation/alerts/${encodeURIComponent(acknowledge.dataset.ackAlert)}/acknowledge`, { method: 'POST' });
      toast('Alert acknowledged.', 'success');
      await loadAll({ quiet: true });
    } catch (error) { toast(error.message, 'error'); }
  }
}

function setupEvents() {
  document.querySelectorAll('.nav-item').forEach(button => button.addEventListener('click', () => setView(button.dataset.view)));
  document.addEventListener('click', handleClick);
  document.addEventListener('submit', event => {
    const form = event.target.closest('[data-review-result]');
    if (form) {
      event.preventDefault();
      handleReviewSubmit(form);
    }
  });
  $('refresh-all').addEventListener('click', () => loadAll());
  $('dataset-form').addEventListener('submit', handleDatasetUpload);
  $('dataset-file').addEventListener('change', event => {
    const drop = event.target.closest('.file-drop');
    drop.classList.toggle('has-file', Boolean(event.target.files[0]));
    const label = drop.querySelector('span');
    label.textContent = event.target.files[0]?.name || 'Drop or choose CSV / JSON';
  });
  $('experiment-form').addEventListener('submit', handleExperimentCreate);
  $('compare-selected').addEventListener('click', compareSelected);
  $('export-experiment').addEventListener('click', exportSelectedExperiment);
  $('review-experiment').addEventListener('change', async event => {
    if (!event.target.value) {
      state.selectedExperiment = null;
      return renderReview();
    }
    try {
      await openExperiment(event.target.value, false);
      event.target.value = state.selectedExperiment.id;
      renderReview();
    } catch (error) { toast(error.message, 'error'); }
  });
  $('version-form').addEventListener('submit', handleVersionCreate);
  $('copy-metrics-endpoint').addEventListener('click', async () => {
    const value = `${window.location.origin}/api/evaluation/metrics`;
    try {
      await navigator.clipboard.writeText(value);
      toast('Metrics endpoint copied.', 'success');
    } catch (_) {
      window.prompt('Copy the metrics endpoint:', value);
    }
  });
}

async function boot() {
  setupEvents();
  const token = authToken();
  if (!token) return window.location.replace('/');
  try {
    const session = await api('/auth/session');
    if (session.user?.role !== 'pio' || !session.user?.isAdmin) {
      toast('PIO administrator access is required.', 'error');
      return setTimeout(() => window.location.replace('/'), 700);
    }
    state.user = session.user;
    $('admin-name').textContent = session.user.fullName || session.user.username || 'Administrator';
    await loadAll();
  } catch (error) {
    setGlobalMessage(error.message || 'Unable to start the control center.');
  }
}

boot();
