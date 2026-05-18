'use strict';

const Database = require('better-sqlite3');
const path = require('path');

/**
 * SQLite database for OTP-based user authentication
 * Handles user registration, password storage, and OTP management
 */

const DB_PATH = process.env.DB_PATH || path.join(__dirname, '../data/auth.db');
const DB_DIR = path.dirname(DB_PATH);

// Ensure data directory exists
const fs = require('fs');
if (!fs.existsSync(DB_DIR)) {
    fs.mkdirSync(DB_DIR, { recursive: true });
}

let db = null;

/**
 * Initialize database connection and create tables if needed
 */
function initializeDatabase() {
    try {
        db = new Database(DB_PATH);
        db.pragma('journal_mode = WAL');
        createTables();
        console.log(`[db] Initialized SQLite at ${DB_PATH}`);
    } catch (err) {
        console.error('[db] Failed to initialize database:', err.message);
        throw err;
    }
}

/**
 * Create necessary tables for user auth
 */
function createTables() {
    // Users table
    db.exec(`
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT UNIQUE NOT NULL COLLATE NOCASE,
      password_hash TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    );
  `);

    // OTP verification table
    db.exec(`
    CREATE TABLE IF NOT EXISTS otp_requests (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT NOT NULL COLLATE NOCASE,
      otp_code TEXT NOT NULL,
      expires_at INTEGER NOT NULL,
      verified INTEGER DEFAULT 0,
      created_at INTEGER NOT NULL,
      verified_at INTEGER
    );
  `);

    // Create indexes for common queries
    db.exec(`
    CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
    CREATE INDEX IF NOT EXISTS idx_otp_email ON otp_requests(email);
    CREATE INDEX IF NOT EXISTS idx_otp_expires ON otp_requests(expires_at);
  `);
}

/**
 * Get database instance (lazy initialization)
 */
function getDB() {
    if (!db) {
        initializeDatabase();
    }
    return db;
}

/**
 * Store a new OTP request
 * @param {string} email
 * @param {string} otpCode - 6-digit OTP
 * @param {number} expiryMinutes - OTP validity in minutes (default 10)
 * @returns {number} OTP request ID
 */
function storeOTP(email, otpCode, expiryMinutes = 10) {
    const db = getDB();
    const now = Math.floor(Date.now() / 1000);
    const expiresAt = now + expiryMinutes * 60;

    const stmt = db.prepare(`
    INSERT INTO otp_requests (email, otp_code, expires_at, created_at)
    VALUES (?, ?, ?, ?)
  `);

    const result = stmt.run(email.toLowerCase(), otpCode, expiresAt, now);
    return result.lastInsertRowid;
}

/**
 * Verify OTP for an email
 * @param {string} email
 * @param {string} otpCode - Code to verify
 * @returns {object} { valid: boolean, reason?: string }
 */
function verifyOTP(email, otpCode) {
    const db = getDB();
    const now = Math.floor(Date.now() / 1000);

    const stmt = db.prepare(`
    SELECT id, expires_at, verified FROM otp_requests
    WHERE email = ? AND otp_code = ?
    ORDER BY created_at DESC
    LIMIT 1
  `);

    const record = stmt.get(email.toLowerCase(), otpCode);

    if (!record) {
        return { valid: false, reason: 'Invalid OTP' };
    }

    if (record.verified) {
        return { valid: false, reason: 'OTP already verified' };
    }

    if (record.expires_at < now) {
        return { valid: false, reason: 'OTP expired' };
    }

    // Mark as verified
    const updateStmt = db.prepare(`
    UPDATE otp_requests
    SET verified = 1, verified_at = ?
    WHERE id = ?
  `);
    updateStmt.run(now, record.id);

    return { valid: true };
}

/**
 * Create a new user with email and password hash
 * @param {string} email
 * @param {string} passwordHash - bcrypt hashed password
 * @returns {object} { success: boolean, userId?: number, error?: string }
 */
function createUser(email, passwordHash) {
    const db = getDB();
    const now = Math.floor(Date.now() / 1000);

    try {
        const stmt = db.prepare(`
      INSERT INTO users (email, password_hash, created_at, updated_at)
      VALUES (?, ?, ?, ?)
    `);

        const result = stmt.run(email.toLowerCase(), passwordHash, now, now);
        return { success: true, userId: result.lastInsertRowid };
    } catch (err) {
        if (err.message.includes('UNIQUE constraint failed')) {
            return { success: false, error: 'Email already registered' };
        }
        return { success: false, error: err.message };
    }
}

/**
 * Look up user by email
 * @param {string} email
 * @returns {object|null} User record or null if not found
 */
function getUserByEmail(email) {
    const db = getDB();

    const stmt = db.prepare(`
    SELECT id, email, password_hash, created_at, updated_at
    FROM users
    WHERE email = ?
  `);

    return stmt.get(email.toLowerCase()) || null;
}

/**
 * Clean up expired OTPs (can run periodically)
 * @returns {number} Number of rows deleted
 */
function cleanupExpiredOTPs() {
    const db = getDB();
    const now = Math.floor(Date.now() / 1000);

    const stmt = db.prepare(`
    DELETE FROM otp_requests
    WHERE expires_at < ? AND verified = 0
  `);

    const result = stmt.run(now);
    return result.changes;
}

/**
 * Close database connection (for graceful shutdown)
 */
function closeDatabase() {
    if (db) {
        db.close();
        db = null;
    }
}

module.exports = {
    initializeDatabase,
    getDB,
    storeOTP,
    verifyOTP,
    createUser,
    getUserByEmail,
    cleanupExpiredOTPs,
    closeDatabase,
};
