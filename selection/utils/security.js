'use strict';

const crypto = require('crypto');

const IS_PROD = process.env.NODE_ENV === 'production';
const configuredSecret = String(process.env.AUTH_TOKEN_SECRET || process.env.JWT_SECRET || '');
if (IS_PROD && configuredSecret.length < 32) {
  throw new Error('AUTH_TOKEN_SECRET (or JWT_SECRET) must contain at least 32 characters in production.');
}
const runtimeSecret = configuredSecret.length >= 32
  ? configuredSecret
  : crypto.randomBytes(32).toString('hex');
if (!IS_PROD && configuredSecret.length < 32) {
  console.warn('[security] Using an ephemeral development signing secret; sessions will reset on restart.');
}

function b64(value) {
  return Buffer.from(value).toString('base64url');
}

function sign(value) {
  return crypto.createHmac('sha256', runtimeSecret).update(value).digest('base64url');
}

function safeEqual(left, right) {
  const a = Buffer.from(String(left || ''));
  const b = Buffer.from(String(right || ''));
  return a.length > 0 && a.length === b.length && crypto.timingSafeEqual(a, b);
}

function issueToken(payload, ttlSeconds) {
  const now = Math.floor(Date.now() / 1000);
  const body = b64(JSON.stringify({ ...payload, iat: now, exp: now + ttlSeconds }));
  return `${body}.${sign(body)}`;
}

function verifyToken(token, expectedType) {
  const [body, signature, extra] = String(token || '').split('.');
  if (!body || !signature || extra || !safeEqual(signature, sign(body))) return null;
  try {
    const payload = JSON.parse(Buffer.from(body, 'base64url').toString('utf8'));
    const now = Math.floor(Date.now() / 1000);
    if (payload.type !== expectedType || !Number.isSafeInteger(payload.exp) || payload.exp <= now) return null;
    return payload;
  } catch (_) {
    return null;
  }
}

function otpDigest(email, otp) {
  return crypto.createHmac('sha256', runtimeSecret)
    .update(`${String(email).trim().toLowerCase()}:${String(otp).trim()}`)
    .digest('hex');
}

function securityHeaders(_req, res, next) {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('Referrer-Policy', 'no-referrer');
  res.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=(), usb=()');
  res.setHeader(
    'Content-Security-Policy',
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; " +
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; " +
    "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
  );
  if (IS_PROD) res.setHeader('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
  next();
}

function createRateLimiter({ name, limit, windowMs }) {
  const buckets = new Map();
  return (req, res, next) => {
    const now = Date.now();
    const key = `${name}:${req.socket?.remoteAddress || req.ip || 'unknown'}`;
    let item = buckets.get(key);
    if (!item || item.resetAt <= now) item = { count: 0, resetAt: now + windowMs };
    item.count += 1;
    buckets.set(key, item);
    if (item.count > limit) {
      res.setHeader('Retry-After', String(Math.max(1, Math.ceil((item.resetAt - now) / 1000))));
      return res.status(429).json({ success: false, error: 'Too many requests. Please try again later.' });
    }
    next();
  };
}

function sessionCookieOptions() {
  return {
    httpOnly: true,
    secure: IS_PROD,
    sameSite: 'strict',
    path: '/',
    maxAge: Number(process.env.AUTH_SESSION_TTL_MS || 8 * 60 * 60 * 1000),
  };
}

module.exports = {
  createRateLimiter,
  issueToken,
  otpDigest,
  safeEqual,
  securityHeaders,
  sessionCookieOptions,
  verifyToken,
};
