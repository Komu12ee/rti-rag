'use strict';

require('dotenv').config();

const express = require('express');
const cookieParser = require('cookie-parser');
const morgan = require('morgan');
const path = require('path');

const PORT = process.env.PORT || 3000;
const IS_PROD = process.env.NODE_ENV === 'production';
const OTP_AUTH_ENABLED = process.env.OTP_AUTH_ENABLED !== 'false';

const { initializeDatabase, closeDatabase } = require('./utils/db-utils');
const { initializeEmailService } = require('./utils/email-utils');
const otpAuthRouter = require('./routes/otp-auth');
const selectRouter = require('./routes/select');

const app = express();

// ─── Logging ────────────────────────────────────────────────────────────────
app.use(morgan(IS_PROD ? 'combined' : 'dev'));

// ─── Initialize OTP Authentication (if enabled) ─────────────────────────────
if (OTP_AUTH_ENABLED) {
    try {
        initializeDatabase();
        initializeEmailService();
        console.log('[server] OTP authentication enabled');
    } catch (err) {
        console.error('[server] Failed to initialize OTP auth:', err.message);
        // Continue anyway - system can still run
    }
}

// ─── Security headers ───────────────────────────────────────────────────────
app.use((_req, res, next) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('X-Frame-Options', 'DENY');
    res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
    next();
});

// ─── Cookie parsing ─────────────────────────────────────────────────────────
app.use(cookieParser());

// ─── Static assets ──────────────────────────────────────────────────────────
app.use(express.static(path.join(__dirname, 'public'), {
    maxAge: IS_PROD ? '7d' : 0,
    etag: true,
}));

// ─── Health check ───────────────────────────────────────────────────────────
app.get('/health', (_req, res) => {
    res.status(200).json({ success: true, status: 'ok' });
});

// ─── OTP Auth routes (/otp-auth/send-otp, /otp-auth/verify-otp, /otp-auth/register, /otp-auth/login, /otp-auth/logout) ───
// express.json() scoped ONLY to /otp-auth — never globally.
if (OTP_AUTH_ENABLED) {
    app.use('/otp-auth', express.json(), otpAuthRouter);
} else {
    console.warn('[server] WARNING: OTP authentication is disabled');
}

// ─── Pipeline Selection routes (/select, /select/launch) ───────────────────
app.use('/select', express.json(), selectRouter);

// ─── SPA fallback ───────────────────────────────────────────────────────────
app.get('*', (_req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'otp-auth.html'));
});

// ─── Start ───────────────────────────────────────────────────────────────────
const server = app.listen(PORT, '0.0.0.0', () => {
    console.log('');
    console.log('═══════════════════════════════════════════════════════════');
    console.log('  CHiPS-RAG  –  Selection & Auth Server');
    console.log('═══════════════════════════════════════════════════════════');
    console.log(`  URL     →  http://0.0.0.0:${PORT}`);
    console.log(`  Mode    →  ${IS_PROD ? 'production' : 'development'}`);
    if (OTP_AUTH_ENABLED) {
        console.log(`  OTP     →  Enabled`);
    }
    console.log('═══════════════════════════════════════════════════════════');
    console.log('');
});

// ─── Graceful shutdown ───────────────────────────────────────────────────────
process.on('SIGTERM', () => {
    console.log('[server] SIGTERM received. Shutting down gracefully...');
    closeDatabase();
    server.close(() => {
        process.exit(0);
    });
});

process.on('SIGINT', () => {
    console.log('[server] SIGINT received. Shutting down gracefully...');
    closeDatabase();
    server.close(() => {
        process.exit(0);
    });
});
