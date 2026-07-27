'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');

const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rti-auth-'));
process.env.AUTH_USERS_FILE = path.join(tempDir, 'users.json');
process.env.AUTH_PIO_USERS_FILE = path.join(tempDir, 'pio_users.json');
const store = require('./auth-store');

test('creates a citizen account with a password hash and authenticates it', async () => {
  const created = await store.createUser({
    fullName: 'Test PIO',
    username: 'test.pio',
    email: 'test.pio@example.gov.in',
    password: 'SecurePass123',
  });
  assert.equal(created.user.username, 'test.pio');
  assert.equal(created.user.role, 'citizen');

  const raw = JSON.parse(fs.readFileSync(store.USERS_FILE, 'utf8'));
  assert.equal(raw.users.length, 1);
  assert.notEqual(raw.users[0].passwordHash, 'SecurePass123');
  assert.match(raw.users[0].passwordHash, /^pbkdf2_sha256\$210000\$/);

  const authenticated = await store.authenticate('test.pio@example.gov.in', 'SecurePass123');
  assert.equal(authenticated.username, 'test.pio');
  assert.equal(await store.authenticate('test.pio', 'wrong-password'), null);
});

test('authenticates a manually managed PIO from the separate JSON store', async () => {
  const passwordHash = await new Promise((resolve, reject) => {
    require('crypto').pbkdf2('ManualPass123', Buffer.from('0123456789abcdef'), 210000, 32, 'sha256', (error, value) => {
      if (error) reject(error);
      else resolve(`pbkdf2_sha256$210000$${Buffer.from('0123456789abcdef').toString('base64')}$${value.toString('base64')}`);
    });
  });
  fs.writeFileSync(store.PIO_USERS_FILE, JSON.stringify({
    version: 1,
    pios: [{ name: 'Manual PIO', email: 'manual.pio@example.gov.in', passwordHash, active: true }],
  }));
  const user = await store.authenticate('manual.pio@example.gov.in', 'ManualPass123', 'pio');
  assert.equal(user.fullName, 'Manual PIO');
  assert.equal(user.role, 'pio');
  assert.equal(await store.authenticate('manual.pio@example.gov.in', 'ManualPass123'), null);
  assert.equal(await store.authenticate('manual.pio@example.gov.in', 'wrong-password', 'pio'), null);
});

test('rejects plaintext PIO credentials', async () => {
  fs.writeFileSync(store.PIO_USERS_FILE, JSON.stringify({
    version: 1,
    pios: [{ name: 'Unsafe PIO', email: 'unsafe.pio@example.gov.in', password: 'PlaintextPass123', active: true }],
  }));
  assert.equal(await store.authenticate('unsafe.pio@example.gov.in', 'PlaintextPass123', 'pio'), null);
});

test('rejects duplicate identity and supports expiring server sessions', async () => {
  const duplicate = await store.createUser({
    fullName: 'Another PIO',
    username: 'test.pio',
    email: 'another@example.gov.in',
    password: 'SecurePass123',
  });
  assert.match(duplicate.error, /already exists/i);

  const user = await store.authenticate('test.pio', 'SecurePass123');
  const token = store.createSession(user);
  assert.equal(store.sessionFromToken(token).user.username, 'test.pio');
  store.deleteSession(token);
  assert.equal(store.sessionFromToken(token), null);
});

test.after(() => fs.rmSync(tempDir, { recursive: true, force: true }));
