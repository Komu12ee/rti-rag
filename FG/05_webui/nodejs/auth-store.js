'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const bcrypt = require('bcryptjs');

const DEFAULT_DATA_DIR = path.resolve(__dirname, '..', 'data');
const USERS_FILE = process.env.AUTH_USERS_FILE || path.join(DEFAULT_DATA_DIR, 'users.json');
const PIO_USERS_FILE = process.env.AUTH_PIO_USERS_FILE || path.join(DEFAULT_DATA_DIR, 'pio_users.json');
const SESSION_TTL_MS = 8 * 60 * 60 * 1000;
const PASSWORD_ITERATIONS = 210000;
const sessions = new Map();

function ensureJsonStore(file, collection) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  if (!fs.existsSync(file)) {
    fs.writeFileSync(file, JSON.stringify({ version: 1, [collection]: [] }, null, 2) + '\n', {
      encoding: 'utf8', mode: 0o600,
    });
  }
}

function ensureStore() {
  ensureJsonStore(USERS_FILE, 'users');
  ensureJsonStore(PIO_USERS_FILE, 'pios');
}

function readStore() {
  ensureStore();
  const parsed = JSON.parse(fs.readFileSync(USERS_FILE, 'utf8'));
  if (!parsed || !Array.isArray(parsed.users)) throw new Error('The JSON user store is invalid.');
  return parsed;
}

function readPioStore() {
  ensureStore();
  const parsed = JSON.parse(fs.readFileSync(PIO_USERS_FILE, 'utf8'));
  if (!parsed || !Array.isArray(parsed.pios)) throw new Error('The JSON PIO user store is invalid.');
  return parsed;
}

function writeStore(store) {
  fs.writeFileSync(USERS_FILE, JSON.stringify(store, null, 2) + '\n', {
    encoding: 'utf8', mode: 0o600,
  });
}

function normalize(value) { return String(value || '').trim().toLowerCase(); }

function publicUser(user) {
  return {
    id: user.id, fullName: user.fullName, username: user.username,
    email: user.email, role: user.role, createdAt: user.createdAt,
  };
}

function normalizePioUser(user) {
  if (!user || typeof user !== 'object' || user.active === false) return null;
  const email = normalize(user.email);
  const username = normalize(user.username);
  const fullName = String(user.fullName || user.name || '').trim();
  if (!email || !fullName || (!user.password && !user.passwordHash)) return null;
  return {
    ...user, id: String(user.id || `pio:${email}`), fullName, username, email, role: 'pio',
  };
}

function hashPassword(password) {
  const salt = crypto.randomBytes(16);
  return new Promise((resolve, reject) => {
    crypto.pbkdf2(password, salt, PASSWORD_ITERATIONS, 32, 'sha256', (error, derived) => {
      if (error) return reject(error);
      resolve(`pbkdf2_sha256$${PASSWORD_ITERATIONS}$${salt.toString('base64')}$${derived.toString('base64')}`);
    });
  });
}

async function verifyPassword(password, storedHash) {
  if (String(storedHash || '').startsWith('pbkdf2_sha256$')) {
    const [, iterationsText, saltText, expectedText] = storedHash.split('$');
    const iterations = Number(iterationsText);
    const salt = Buffer.from(saltText || '', 'base64');
    const expected = Buffer.from(expectedText || '', 'base64');
    if (!Number.isSafeInteger(iterations) || iterations < 100000 || !salt.length || !expected.length) return false;
    const derived = await new Promise((resolve, reject) => {
      crypto.pbkdf2(password, salt, iterations, expected.length, 'sha256', (error, value) => error ? reject(error) : resolve(value));
    });
    return derived.length === expected.length && crypto.timingSafeEqual(derived, expected);
  }
  return bcrypt.compare(password, storedHash || '$2a$12$SFLvSxL5YpBPrR4xU0dKJu0chSyfmxu24XfV8HfBkM0oHh2QbL9iK');
}

function validateSignup(input) {
  const fullName = String(input.fullName || '').trim();
  const username = normalize(input.username);
  const email = normalize(input.email);
  const password = String(input.password || '');
  if (fullName.length < 2 || fullName.length > 100) return { error: 'Full name must be between 2 and 100 characters.' };
  if (!/^[a-z0-9._-]{3,40}$/.test(username)) return { error: 'User ID must be 3-40 characters using letters, numbers, dot, underscore, or hyphen.' };
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 160) return { error: 'Enter a valid official email address.' };
  if (password.length < 8 || password.length > 128) return { error: 'Password must be between 8 and 128 characters.' };
  return { fullName, username, email, password };
}

async function createUser(input) {
  const value = validateSignup(input);
  if (value.error) return value;
  const store = readStore();
  const duplicate = store.users.some(user => normalize(user.username) === value.username || normalize(user.email) === value.email)
    || readPioStore().pios.map(normalizePioUser).filter(Boolean)
      .some(user => normalize(user.username) === value.username || normalize(user.email) === value.email);
  if (duplicate) return { error: 'An account already exists for this User ID or email.' };
  const now = new Date().toISOString();
  const user = {
    id: crypto.randomUUID(), fullName: value.fullName, username: value.username,
    email: value.email, role: 'citizen', passwordHash: await hashPassword(value.password),
    createdAt: now, updatedAt: now,
  };
  store.users.push(user);
  writeStore(store);
  return { user: publicUser(user) };
}

async function authenticate(identifier, password, accountType = 'citizen') {
  const key = normalize(identifier);
  const suppliedPassword = String(password || '');
  const requestedRole = normalize(accountType);
  if (!key || !suppliedPassword || !['citizen', 'pio'].includes(requestedRole)) return null;
  const pioUser = readPioStore().pios.map(normalizePioUser).filter(Boolean)
    .find(item => normalize(item.username) === key || normalize(item.email) === key);
  if (requestedRole === 'pio' && pioUser) {
    let matches;
    if (pioUser.passwordHash) {
      matches = await verifyPassword(suppliedPassword, pioUser.passwordHash);
    } else {
      const supplied = Buffer.from(suppliedPassword);
      const stored = Buffer.from(String(pioUser.password));
      matches = supplied.length === stored.length && crypto.timingSafeEqual(supplied, stored);
    }
    return matches ? publicUser({ ...pioUser, role: 'pio' }) : null;
  }
  if (requestedRole === 'pio') return null;
  const user = readStore().users.find(item => normalize(item.username) === key || normalize(item.email) === key);
  const dummyHash = 'pbkdf2_sha256$210000$MDEyMzQ1Njc4OWFiY2RlZg==$yXaBmnT5AM+GOthdJjhGO7r41Q/tPXfaXk+fsXekx44=';
  const matches = await verifyPassword(suppliedPassword, user?.passwordHash || dummyHash);
  return user && matches ? publicUser({ ...user, role: 'citizen' }) : null;
}

function createSession(user) {
  const token = crypto.randomBytes(32).toString('base64url');
  sessions.set(token, { user, expiresAt: Date.now() + SESSION_TTL_MS });
  return token;
}

function sessionFromToken(token) {
  const key = String(token || '');
  const session = sessions.get(key);
  if (!session) return null;
  if (session.expiresAt <= Date.now()) { sessions.delete(key); return null; }
  return session;
}

function deleteSession(token) { sessions.delete(String(token || '')); }

module.exports = { USERS_FILE, PIO_USERS_FILE, authenticate, createSession, createUser, deleteSession, ensureStore, sessionFromToken };
