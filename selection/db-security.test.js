'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');

const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rti-otp-security-'));
process.env.DB_PATH = path.join(tempDir, 'auth.db');
process.env.AUTH_TOKEN_SECRET = 'test-secret-that-is-longer-than-thirty-two-characters';
let store;
try {
  store = require('./utils/db-utils');
} catch (error) {
  if (error.code !== 'MODULE_NOT_FOUND' || !String(error.message).includes('better-sqlite3')) throw error;
}

test('OTP values are hashed at rest, one-time, and attempt-limited', {
  skip: store ? false : 'better-sqlite3 is not installed in this checkout',
}, () => {
  store.initializeDatabase();
  store.storeOTP('user@example.gov.in', '123456', 10);

  const row = store.getDB().prepare(
    'SELECT otp_code, attempts, verified FROM otp_requests ORDER BY id DESC LIMIT 1'
  ).get();
  assert.notEqual(row.otp_code, '123456');
  assert.equal(row.otp_code.length, 64);

  for (let index = 0; index < 5; index += 1) {
    assert.equal(store.verifyOTP('user@example.gov.in', '000000').valid, false);
  }
  assert.match(
    store.verifyOTP('user@example.gov.in', '123456').reason,
    /too many/i
  );

  store.storeOTP('second@example.gov.in', '654321', 10);
  assert.equal(store.verifyOTP('second@example.gov.in', '654321').valid, true);
  assert.equal(store.verifyOTP('second@example.gov.in', '654321').valid, false);
});

test.after(() => {
  store?.closeDatabase();
  fs.rmSync(tempDir, { recursive: true, force: true });
});
