'use strict';

const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');
const morgan = require('morgan');
const path = require('path');
const { router: authRouter } = require('./routes/auth-json');
const jsonAuth = require('./middleware/json-auth');
const { ensureStore } = require('./auth-store');
const {
  corsOrigin,
  createRateLimiter,
  securityHeaders,
} = require('./security');

const PORT = process.env.PORT || 3002;
const FLASK_PORT = process.env.FLASK_PORT || 5000;
const FLASK_URL = `http://localhost:${FLASK_PORT}`;
const IS_PROD = process.env.NODE_ENV === 'production';

const app = express();
ensureStore();
app.use(express.json({ limit: '32kb' }));

// Browser origins are operator-controlled; arbitrary origins are rejected.
app.use(require('cors')({ origin: corsOrigin, credentials: true }));
app.use((error, _req, res, next) => {
  if (!error) return next();
  if (error.status === 403) {
    return res.status(403).json({ success: false, error: 'Request origin is not allowed.' });
  }
  return next(error);
});

// ─── Logging ────────────────────────────────────────────────────────────────
app.use(morgan(IS_PROD ? 'combined' : 'dev'));

// ─── Security headers ───────────────────────────────────────────────────────
app.use(securityHeaders);

const authLimiter = createRateLimiter({
  scope: 'auth', limit: Number(process.env.AUTH_RATE_LIMIT || 10), windowMs: 60_000,
});
const queryLimiter = createRateLimiter({
  scope: 'query', limit: Number(process.env.QUERY_RATE_LIMIT || 30), windowMs: 60_000,
});
const uploadLimiter = createRateLimiter({
  scope: 'upload', limit: Number(process.env.UPLOAD_RATE_LIMIT || 5), windowMs: 60 * 60_000,
});

// ─── Static assets ──────────────────────────────────────────────────────────
app.use(
  express.static(path.join(__dirname, 'public'), {
    maxAge: IS_PROD ? '7d' : 0,
    etag: true,
  })
);

// ─── Proxies ─────────────────────────────────────────────────────────────────
// hpm v3 strips the mount path before forwarding (e.g. /api/query → /query).
// pathRewrite as a FUNCTION (not object) re-adds the prefix.
// Object form { '^/api': '/api' } is silently ignored in hpm v3.

const apiProxy = createProxyMiddleware({
  target: FLASK_URL,
  changeOrigin: true,
  selfHandleResponse: false,
  pathRewrite: (path) => '/api' + path,   // /query → /api/query
  on: {
    error: (err, _req, res) => {
      console.error('[proxy] API error:', err.message);
      if (!res.headersSent) {
        res.status(502).json({
          success: false,
          error: 'RAG backend is unreachable. Is Flask running?',
        });
      }
    },
    proxyReq: (_proxyReq, req) => {
      if (!IS_PROD) {
        console.log(`[proxy] → ${req.method} ${FLASK_URL}${req.url}`);
      }
    },
  },
});

const pdfProxy = createProxyMiddleware({
  target: FLASK_URL,
  changeOrigin: true,
  pathRewrite: (path) => '/01_preprocessing' + path,
  on: {
    error: (err, _req, res) => {
      console.error('[proxy] PDF error:', err.message);
      if (!res.headersSent) {
        res.status(502).json({ error: 'PDF service unavailable' });
      }
    },
  },
});

// Authentication is enforced before proxying; Flask independently protects
// PIO/evaluation routes so direct-backend access cannot bypass authorization.
app.use('/auth', authLimiter, authRouter);
app.use('/api/pio/upload-pdf', uploadLimiter);
app.use('/api', queryLimiter, jsonAuth, (req, res, next) => {
  const pioModeValue = String(req.body?.pio_mode ?? '').trim().toLowerCase();
  const requestsPioAccess = req.path.startsWith('/pio/')
    || req.path.startsWith('/web-verification/')
    || ['true', '1', 'yes', 'on'].includes(pioModeValue);
  if (req.user.role === 'service' && req.path === '/evaluation/metrics') {
    return next();
  }
  if (req.user.role !== 'pio' && requestsPioAccess) {
    return res.status(403).json({ success: false, error: 'PIO mode is restricted to authorised PIO accounts.' });
  }
  next();
}, apiProxy);
app.use('/01_preprocessing', uploadLimiter, jsonAuth, pdfProxy);

// ─── SPA fallback ───────────────────────────────────────────────────────────
app.get('*', (_req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// ─── Start ───────────────────────────────────────────────────────────────────
app.listen(PORT, '0.0.0.0', () => {
  console.log('');
  console.log('═══════════════════════════════════════════════════════════');
  console.log('  CHiPS-RAG  –  Express UI Server');
  console.log('═══════════════════════════════════════════════════════════');
  console.log(`  UI      →  http://0.0.0.0:${PORT}`);
  console.log(`  Flask   →  ${FLASK_URL}  (proxied with authorization)`);
  console.log(`  Mode    →  ${IS_PROD ? 'production' : 'development'}`);
  console.log('═══════════════════════════════════════════════════════════');
  console.log('');
});
