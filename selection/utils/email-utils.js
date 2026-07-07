'use strict';

const nodemailer = require('nodemailer');

let transporter = null;

/**
 * Initialize email transporter
 * Reads SMTP config from environment variables
 */
function initializeEmailService() {
    const emailConfig = {
        host: process.env.SMTP_HOST,
        port: parseInt(process.env.SMTP_PORT || '587', 10),
        secure: process.env.SMTP_SECURE === 'true', // true for 465, false for 587
        auth: {
            user: process.env.SMTP_USER,
            pass: process.env.SMTP_PASSWORD || process.env.SMTP_PASS,
        },
    };

    // Validate required config
    if (!emailConfig.host || !emailConfig.auth.user || !emailConfig.auth.pass) {
        console.warn('[email] SMTP credentials not configured. Email service disabled.');
        return false;
    }

    try {
        transporter = nodemailer.createTransport(emailConfig);
        console.log('[email] Email service initialized');
        return true;
    } catch (err) {
        console.error('[email] Failed to initialize email service:', err.message);
        return false;
    }
}

/**
 * Send OTP to email
 * @param {string} recipientEmail
 * @param {string} otpCode
 * @returns {Promise<object>} { success: boolean, error?: string }
 */
async function sendOTPEmail(recipientEmail, otpCode) {
    if (!transporter) {
        return { success: false, error: 'Email service not configured' };
    }

    const senderName = process.env.SMTP_SENDER_NAME || 'CHiPS-RAG';
    const senderEmail = process.env.SMTP_FROM_EMAIL || process.env.SMTP_USER;

    const mailOptions = {
        from: `${senderName} <${senderEmail}>`,
        to: recipientEmail,
        subject: 'Your OTP for CHiPS-RAG Sign Up',
        html: `
      <!DOCTYPE html>
      <html>
      <head>
        <style>
          body { font-family: 'IBM Plex Sans', sans-serif; color: #333; }
          .container { max-width: 600px; margin: 0 auto; padding: 20px; }
          .header { background: #f5f5f5; padding: 20px; border-radius: 4px; margin-bottom: 20px; }
          .brand { font-size: 24px; font-weight: 600; margin-bottom: 5px; }
          .otp-box { background: #f9f9f9; border: 2px solid #e0e0e0; padding: 20px; border-radius: 4px; text-align: center; margin: 20px 0; }
          .otp-code { font-size: 40px; font-weight: 700; letter-spacing: 6px; font-family: 'IBM Plex Mono', monospace; color: #000; }
          .expiry { color: #999; font-size: 14px; margin-top: 10px; }
          .footer { color: #999; font-size: 12px; margin-top: 30px; }
        </style>
      </head>
      <body>
        <div class="container">
          <div class="header">
            <div class="brand">CHiPS-RAG</div>
            <div>Document Assistant</div>
          </div>
          
          <p>Hello,</p>
          <p>Your OTP for signing up on CHiPS-RAG is:</p>
          
          <div class="otp-box">
            <div class="otp-code">${otpCode}</div>
            <div class="expiry">This OTP will expire in 10 minutes</div>
          </div>
          
          <p>If you did not request this OTP, please ignore this email.</p>
          
          <div class="footer">
            <p>© Government of Chhattisgarh · CHiPS-RAG</p>
          </div>
        </div>
      </body>
      </html>
    `,
        text: `Your OTP for CHiPS-RAG is: ${otpCode}\nThis OTP will expire in 10 minutes.`,
    };

    try {
        await transporter.sendMail(mailOptions);
        console.log(`[email] OTP sent to ${recipientEmail}`);
        return { success: true };
    } catch (err) {
        console.error('[email] Failed to send OTP:', err.message);
        return { success: false, error: err.message };
    }
}

/**
 * Verify email transporter is working (optional test)
 */
async function verifyEmailConnection() {
    if (!transporter) {
        return { success: false, error: 'Email service not initialized' };
    }

    try {
        await transporter.verify();
        console.log('[email] SMTP connection verified');
        return { success: true };
    } catch (err) {
        console.error('[email] SMTP connection failed:', err.message);
        return { success: false, error: err.message };
    }
}

module.exports = {
    initializeEmailService,
    sendOTPEmail,
    verifyEmailConnection,
};
