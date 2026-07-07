'use strict';

const express = require('express');
const bcrypt = require('bcryptjs');
const { generateOTP, isValidOTPFormat } = require('../utils/otp-utils');
const { sendOTPEmail } = require('../utils/email-utils');
const { storeOTP, verifyOTP, createUser, getUserByEmail } = require('../utils/db-utils');

const router = express.Router();

// Email validation regex
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PASSWORD_MIN_LENGTH = 8;

/**
 * POST /otp-auth/send-otp
 * 
 * Request OTP for email (signup or password reset)
 * Body: { email: string }
 * 
 * Success → 200  { success: true, message: "OTP sent to email" }
 * Failure → 400  { success: false, error: <message> }
 */
router.post('/send-otp', async (req, res) => {
    const { email } = req.body || {};

    // Validate email
    if (!email || typeof email !== 'string') {
        return res.status(400).json({ success: false, error: 'Email is required' });
    }

    if (!EMAIL_REGEX.test(email.trim())) {
        return res.status(400).json({ success: false, error: 'Invalid email format' });
    }

    const cleanEmail = email.trim().toLowerCase();

    // Generate OTP
    const otp = generateOTP();
    console.log(`[otp-auth] Generated OTP for ${cleanEmail}: ${otp}`);

    // Store OTP (10 minute expiry)
    try {
        storeOTP(cleanEmail, otp, 10);
    } catch (err) {
        console.error('[otp-auth] Failed to store OTP:', err.message);
        return res.status(500).json({ success: false, error: 'Failed to process request' });
    }

    // Send OTP email
    const emailResult = await sendOTPEmail(cleanEmail, otp);
    if (!emailResult.success) {
        return res.status(500).json({ success: false, error: 'Failed to send OTP email' });
    }

    return res.status(200).json({
        success: true,
        message: 'OTP sent to your email',
    });
});

/**
 * POST /otp-auth/verify-otp
 * 
 * Verify OTP and return verification token
 * Body: { email: string, otp: string }
 * 
 * Success → 200  { success: true, verificationToken: <token> }
 * Failure → 400  { success: false, error: <message> }
 */
router.post('/verify-otp', (req, res) => {
    const { email, otp } = req.body || {};

    // Validate inputs
    if (!email || typeof email !== 'string') {
        return res.status(400).json({ success: false, error: 'Email is required' });
    }

    if (!otp || typeof otp !== 'string') {
        return res.status(400).json({ success: false, error: 'OTP is required' });
    }

    if (!isValidOTPFormat(otp)) {
        return res.status(400).json({ success: false, error: 'OTP must be 6 digits' });
    }

    const cleanEmail = email.trim().toLowerCase();

    // Verify OTP
    const result = verifyOTP(cleanEmail, otp.trim());
    if (!result.valid) {
        return res.status(400).json({ success: false, error: result.reason });
    }

    // Generate verification token (short-lived, contains email)
    const verificationToken = Buffer.from(JSON.stringify({
        email: cleanEmail,
        verified: true,
        iat: Math.floor(Date.now() / 1000),
    })).toString('base64');

    return res.status(200).json({
        success: true,
        verificationToken,
    });
});

/**
 * POST /otp-auth/register
 * 
 * Complete registration with password
 * Body: { email: string, password: string, confirmPassword: string, verificationToken: string }
 * 
 * Success → 201  { success: true, message: "Registration successful" }
 * Failure → 400  { success: false, error: <message> }
 */
router.post('/register', async (req, res) => {
    const { email, password, confirmPassword, verificationToken } = req.body || {};

    // Validate verification token
    if (!verificationToken || typeof verificationToken !== 'string') {
        return res.status(400).json({ success: false, error: 'Verification token is required' });
    }

    let tokenData;
    try {
        tokenData = JSON.parse(Buffer.from(verificationToken, 'base64').toString());
    } catch (err) {
        return res.status(400).json({ success: false, error: 'Invalid verification token' });
    }

    if (!tokenData.verified || !tokenData.email) {
        return res.status(400).json({ success: false, error: 'Invalid verification token' });
    }

    const cleanEmail = email ? email.trim().toLowerCase() : '';

    // Verify token email matches request email
    if (cleanEmail !== tokenData.email) {
        return res.status(400).json({ success: false, error: 'Email mismatch' });
    }

    // Validate password
    if (!password || typeof password !== 'string') {
        return res.status(400).json({ success: false, error: 'Password is required' });
    }

    if (password.length < PASSWORD_MIN_LENGTH) {
        return res.status(400).json({
            success: false,
            error: `Password must be at least ${PASSWORD_MIN_LENGTH} characters`
        });
    }

    if (password !== confirmPassword) {
        return res.status(400).json({ success: false, error: 'Passwords do not match' });
    }

    // Check if user already exists
    const existingUser = getUserByEmail(cleanEmail);
    if (existingUser) {
        return res.status(400).json({ success: false, error: 'Email already registered' });
    }

    // Hash password (bcryptjs with salt rounds 10)
    let passwordHash;
    try {
        passwordHash = await bcrypt.hash(password, 10);
    } catch (err) {
        console.error('[otp-auth] Password hashing failed:', err.message);
        return res.status(500).json({ success: false, error: 'Registration failed' });
    }

    // Create user
    try {
        const userResult = createUser(cleanEmail, passwordHash);
        if (!userResult.success) {
            return res.status(400).json({ success: false, error: userResult.error });
        }

        console.log(`[otp-auth] New user registered: ${cleanEmail}`);

        return res.status(201).json({
            success: true,
            message: 'Registration successful. Please log in.',
        });
    } catch (err) {
        console.error('[otp-auth] Registration failed:', err.message);
        return res.status(500).json({ success: false, error: 'Registration failed' });
    }
});

/**
 * POST /otp-auth/login
 * 
 * Login with email and password (after OTP signup)
 * Body: { email: string, password: string }
 * 
 * Success → 200  { success: true, token: <jwt>, user: { email } }
 * Failure → 401  { success: false, error: "Invalid credentials" }
 */
router.post('/login', async (req, res) => {
    const { email, password } = req.body || {};

    // Validate inputs
    if (!email || typeof email !== 'string' || !password || typeof password !== 'string') {
        return res.status(400).json({ success: false, error: 'Email and password are required' });
    }

    const cleanEmail = email.trim().toLowerCase();

    // Look up user
    const user = getUserByEmail(cleanEmail);
    if (!user) {
        // Timing-safe: run dummy compare
        await bcrypt.compare(password, '$2b$10$invalidsaltinvalidsaltinvalidsa.invalidhashxxxxxxxx');
        return res.status(401).json({ success: false, error: 'Invalid credentials' });
    }

    // Verify password
    const match = await bcrypt.compare(password, user.password_hash);
    if (!match) {
        return res.status(401).json({ success: false, error: 'Invalid credentials' });
    }

    console.log(`[otp-auth] Login successful: ${cleanEmail}`);

    // Set session cookie (simple, no JWT)
    res.cookie('chips_rag_session', cleanEmail, {
        httpOnly: true,
        sameSite: 'strict',
        maxAge: 7 * 24 * 60 * 60 * 1000 // 7 days
    });

    return res.status(200).json({
        success: true,
        user: { email: cleanEmail },
    });
});

/**
 * POST /otp-auth/logout
 * Client-side logout — tells frontend to clear its token.
 * (Stateless JWT: no server-side invalidation unless you add a denylist.)
 */
router.post('/logout', (_req, res) => {
    res.json({ success: true });
});

module.exports = router;
