'use strict';

const express = require('express');
const { authenticate, createSession, createUser, deleteSession, sessionFromToken } = require('../auth-store');
const router = express.Router();

function bearerToken(req) {
  const header = String(req.headers.authorization || '');
  return header.startsWith('Bearer ') ? header.slice(7).trim() : '';
}

router.post('/signup', async (req, res) => {
  try {
    const result = await createUser(req.body || {});
    if (result.error) return res.status(400).json({ success: false, error: result.error });
    return res.status(201).json({ success: true, user: result.user });
  } catch (error) {
    console.error('[auth] Signup failed:', error.message);
    return res.status(500).json({ success: false, error: 'Account could not be created.' });
  }
});

router.post('/login', async (req, res) => {
  try {
    const { identifier, username, password, accountType } = req.body || {};
    const user = await authenticate(identifier || username, password, accountType || 'citizen');
    if (!user) return res.status(401).json({ success: false, error: 'Invalid User ID/email or password.' });
    return res.json({ success: true, token: createSession(user), user });
  } catch (error) {
    console.error('[auth] Login failed:', error.message);
    return res.status(500).json({ success: false, error: 'Sign in is temporarily unavailable.' });
  }
});

router.get('/session', (req, res) => {
  const session = sessionFromToken(bearerToken(req));
  if (!session) return res.status(401).json({ success: false, error: 'Session expired.' });
  return res.json({ success: true, user: session.user });
});

router.post('/logout', (req, res) => {
  deleteSession(bearerToken(req));
  return res.json({ success: true });
});

module.exports = { router, bearerToken };
