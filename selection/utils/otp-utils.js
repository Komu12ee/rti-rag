'use strict';

const crypto = require('crypto');

/**
 * Generate a cryptographically secure 6-digit OTP
 * Uses CSPRNG (crypto.randomBytes) for security
 * @returns {string} 6-digit OTP code
 */
function generateOTP() {
    // Generate 3 random bytes (24 bits)
    // This gives us a range of 0 to 16,777,215
    // We'll use modulo to get 0-999999 range
    const randomBytes = crypto.randomBytes(3);
    const randomInt = (randomBytes[0] << 16) | (randomBytes[1] << 8) | randomBytes[2];
    const otp = randomInt % 1000000;

    // Pad with zeros to ensure 6 digits
    return String(otp).padStart(6, '0');
}

/**
 * Validate OTP format (6 digits)
 * @param {string} otp
 * @returns {boolean}
 */
function isValidOTPFormat(otp) {
    return /^\d{6}$/.test(String(otp).trim());
}

/**
 * In-memory OTP store with expiry (alternative to DB storage)
 * Useful for temporary OTP storage during development
 */
class InMemoryOTPStore {
    constructor() {
        this.store = new Map();
        this.cleanupInterval = null;
    }

    /**
     * Store OTP in memory
     * @param {string} email
     * @param {string} otpCode
     * @param {number} expiryMinutes
     */
    store(email, otpCode, expiryMinutes = 10) {
        const expiresAt = Date.now() + expiryMinutes * 60 * 1000;
        this.store.set(email.toLowerCase(), {
            code: otpCode,
            expiresAt,
            verified: false,
        });
    }

    /**
     * Verify OTP from memory
     * @param {string} email
     * @param {string} otpCode
     * @returns {object} { valid: boolean, reason?: string }
     */
    verify(email, otpCode) {
        const record = this.store.get(email.toLowerCase());

        if (!record) {
            return { valid: false, reason: 'No OTP found for this email' };
        }

        if (Date.now() > record.expiresAt) {
            this.store.delete(email.toLowerCase());
            return { valid: false, reason: 'OTP expired' };
        }

        if (record.verified) {
            return { valid: false, reason: 'OTP already verified' };
        }

        if (record.code !== otpCode) {
            return { valid: false, reason: 'Invalid OTP' };
        }

        record.verified = true;
        return { valid: true };
    }

    /**
     * Clean up memory store periodically
     */
    cleanup() {
        const now = Date.now();
        for (const [email, record] of this.store.entries()) {
            if (now > record.expiresAt) {
                this.store.delete(email);
            }
        }
    }

    /**
     * Start automatic cleanup (every 5 minutes)
     */
    startCleanup() {
        this.cleanup();
        if (!this.cleanupInterval) {
            this.cleanupInterval = setInterval(() => this.cleanup(), 5 * 60 * 1000);
        }
    }

    /**
     * Stop automatic cleanup
     */
    stopCleanup() {
        if (this.cleanupInterval) {
            clearInterval(this.cleanupInterval);
            this.cleanupInterval = null;
        }
    }
}

module.exports = {
    generateOTP,
    isValidOTPFormat,
    InMemoryOTPStore,
};
