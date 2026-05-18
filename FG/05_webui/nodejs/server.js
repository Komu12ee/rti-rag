'use strict';

const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');
const morgan = require('morgan');
const path = require('path');
const authRoutes = require('./routes/auth');

const PORT = process.env.PORT || 3002;
const FLASK_PORT = process.env.FLASK_PORT || 5002;
const FLASK_URL = `http://localhost:${FLASK_PORT}`;
const IS_PROD = process.env.NODE_ENV === 'production';
const authMiddleware = require('./middleware/auth');

const app = express();

// Allow selection server (http://localhost:3000) to access pipeline UIs
app.use(require('cors')({ origin: 'http://localhost:3000', credentials: true }));

// Parse JSON bodies for /auth/login requests
app.use(express.json());

// ─── Logging ────────────────────────────────────────────────────────────────
app.use(morgan(IS_PROD ? 'combined' : 'dev'));

// ─── Security headers ───────────────────────────────────────────────────────
app.use((_req, res, next) => {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
  next();
});

// ─── Static assets ──────────────────────────────────────────────────────────
app.use(
  express.static(path.join(__dirname, 'public'), {
    maxAge: IS_PROD ? '7d' : 0,
    etag: true,
  })
);

// Auth endpoints (/auth/login, /auth/logout)
app.use('/auth', authRoutes);



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

// JWT guard runs first, then proxy
app.use('/api', authMiddleware, apiProxy);
app.use('/01_preprocessing', authMiddleware, pdfProxy);

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
  console.log(`  Flask   →  ${FLASK_URL}  (proxied, JWT-guarded)`);
  console.log(`  Mode    →  ${IS_PROD ? 'production' : 'development'}`);
  console.log('═══════════════════════════════════════════════════════════');
  console.log('');
});