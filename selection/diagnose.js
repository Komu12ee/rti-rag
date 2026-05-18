#!/usr/bin/env node

/**
 * Diagnostic script to check OTP auth setup
 * Run: node diagnose.js
 */

const fs = require('fs');
const path = require('path');

const rootDir = __dirname;

console.log('\n═══════════════════════════════════════════════════════════');
console.log('  OTP Auth System Diagnostic');
console.log('═══════════════════════════════════════════════════════════\n');

// Check 1: Files exist
console.log('✓ Checking files...');
const requiredFiles = [
    'utils/db-utils.js',
    'utils/otp-utils.js',
    'utils/email-utils.js',
    'routes/otp-auth.js',
    'middleware/auth.js',
    'public/otp-auth.js',
    'public/otp-auth.css',
    'README.md',
];

let filesOk = true;
requiredFiles.forEach(file => {
    const filePath = path.join(rootDir, file);
    if (fs.existsSync(filePath)) {
        console.log(`  ✅ ${file}`);
    } else {
        console.log(`  ❌ ${file} NOT FOUND`);
        filesOk = false;
    }
});

if (!filesOk) {
    console.log('\n❌ Some files are missing! Regenerate them.');
    process.exit(1);
}

// Check 2: Dependencies installed
console.log('\n✓ Checking npm dependencies...');
try {
    const pkg = JSON.parse(fs.readFileSync(path.join(rootDir, '../CHiPS/05_webui/nodejs/package.json'), 'utf8'));
    const required = ['better-sqlite3', 'nodemailer', 'bcryptjs', 'dotenv', 'cookie-parser'];

    required.forEach(dep => {
        if (pkg.dependencies[dep]) {
            console.log(`  ✅ ${dep}@${pkg.dependencies[dep]}`);
        } else {
            console.log(`  ❌ ${dep} NOT IN package.json`);
        }
    });
} catch (err) {
    console.log(`  ❌ Error reading package.json: ${err.message}`);
    process.exit(1);
}

// Check 3: .env file
console.log('\n✓ Checking .env configuration...');
try {
    const envPath = path.join(rootDir, '../CHiPS/05_webui/nodejs/.env');
    if (fs.existsSync(envPath)) {
        const env = fs.readFileSync(envPath, 'utf8');
        const hasSMTP = env.includes('SMTP_HOST');
        const hasSessionConfig = env.includes('SESSION_SECRET') || env.includes('CHIPS_RAG_SESSION');

        if (hasSessionConfig) console.log('  ✅ session-related secret/config found');
        else console.log('  ⚠️  no session secret found (session cookie flow may still work)');

        if (hasSMTP) console.log('  ✅ SMTP settings found');
        else console.log('  ⚠️  SMTP settings not configured (OTP emails won\'t send)');
    } else {
        console.log('  ⚠️  .env file not found (will use defaults)');
    }
} catch (err) {
    console.log(`  ❌ Error reading .env: ${err.message}`);
}