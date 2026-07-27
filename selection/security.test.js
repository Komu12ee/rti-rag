'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

process.env.AUTH_TOKEN_SECRET = 'test-secret-that-is-longer-than-thirty-two-characters';
const { issueToken, otpDigest, verifyToken } = require('./utils/security');

test('signed tokens reject tampering and expire by type', () => {
  const token = issueToken({ type: 'session', email: 'user@example.gov.in' }, 60);
  assert.equal(verifyToken(token, 'session').email, 'user@example.gov.in');
  assert.equal(verifyToken(`${token}x`, 'session'), null);
  assert.equal(verifyToken(token, 'email-verification'), null);
});

test('OTP values are stored as keyed digests', () => {
  const digest = otpDigest('user@example.gov.in', '123456');
  assert.notEqual(digest, '123456');
  assert.equal(digest.length, 64);
});
