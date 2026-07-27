'use strict';

const crypto = require('crypto');

function boolEnv(name, fallback = false) {
  const value = String(process.env[name] ?? fallback).trim().toLowerCase();
  return ['1', 'true', 'yes', 'on'].includes(value);
}

function clientIp(req) {
  if (boolEnv('TRUST_PROXY_HEADERS')) {
    const forwarded = String(req.headers['x-forwarded-for'] || '').split(',')[0].trim();
    if (forwarded) return forwarded.slice(0, 64);
  }
  return String(req.socket?.remoteAddress || req.ip || 'unknown').slice(0, 64);
}

function createRateLimiter({ limit, windowMs, scope }) {
  const buckets = new Map();
  const maxKeys = Math.max(100, Number(process.env.SECURITY_RATE_LIMIT_MAX_KEYS || 20000));
  return function rateLimiter(req, res, next) {
    const now = Date.now();
    const key = `${scope}:${clientIp(req)}`;
    let bucket = buckets.get(key);
    if (!bucket || bucket.resetAt <= now) {
      bucket = { count: 0, resetAt: now + windowMs };
      buckets.set(key, bucket);
    }
    bucket.count += 1;
    if (buckets.size > maxKeys) {
      for (const [itemKey, item] of buckets) {
        if (item.resetAt <= now) buckets.delete(itemKey);
        if (buckets.size <= maxKeys) break;
      }
    }
    if (bucket.count > limit) {
      res.setHeader('Retry-After', String(Math.max(1, Math.ceil((bucket.resetAt - now) / 1000))));
      return res.status(429).json({ success: false, error: 'Too many requests. Please try again later.' });
    }
    return next();
  };
}

function securityHeaders(req, res, next) {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('Referrer-Policy', 'no-referrer');
  res.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=(), usb=()');
  res.setHeader(
    'Content-Security-Policy',
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; " +
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; " +
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
  );
  if (req.path.startsWith('/api/') || req.path.startsWith('/auth/')) {
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('Pragma', 'no-cache');
  }
  if (boolEnv('ENABLE_HSTS')) {
    res.setHeader('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
  }
  next();
}

function allowedOrigins() {
  return new Set(String(
    process.env.SECURITY_ALLOWED_ORIGINS ||
    'http://localhost:3000,http://localhost:3002,http://127.0.0.1:3000,http://127.0.0.1:3002'
  ).split(',').map(value => value.trim().replace(/\/$/, '')).filter(Boolean));
}

function corsOrigin(origin, callback) {
  if (!origin || allowedOrigins().has(String(origin).replace(/\/$/, ''))) return callback(null, true);
  const error = new Error('Request origin is not allowed.');
  error.status = 403;
  return callback(error);
}

function safeTokenEqual(left, right) {
  const a = Buffer.from(String(left || ''));
  const b = Buffer.from(String(right || ''));
  return a.length > 0 && a.length === b.length && crypto.timingSafeEqual(a, b);
}

module.exports = {
  boolEnv,
  clientIp,
  corsOrigin,
  createRateLimiter,
  safeTokenEqual,
  securityHeaders,
};
