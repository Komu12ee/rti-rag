/**
 * OTP Authentication Layer
 * Wrapper that conditionally displays OTP signup/login or the main app
 * 
 * Signup Flow: email → OTP verification → password setup
 * Login Flow: email + password
 */

'use strict';

// ── Session storage for OTP auth ─────────────────────────────────────────────
const OTP_SESSION_KEY = 'otp_auth_token';
const USER_EMAIL_KEY = 'user_email';
const TOKEN_KEY = 'chips_rag_token';
const USER_KEY = 'chips_rag_user';

const otpSession = {
  saveToken(token, email) {
    sessionStorage.setItem(OTP_SESSION_KEY, token);
    sessionStorage.setItem(USER_EMAIL_KEY, email);
  },
  getToken() {
    return sessionStorage.getItem(OTP_SESSION_KEY);
  },
  getEmail() {
    return sessionStorage.getItem(USER_EMAIL_KEY);
  },
  clear() {
    sessionStorage.removeItem(OTP_SESSION_KEY);
    sessionStorage.removeItem(USER_EMAIL_KEY);
  },
  exists() {
    return !!sessionStorage.getItem(OTP_SESSION_KEY);
  },
};

// ── OTP Auth Screen Manager ──────────────────────────────────────────────────
class OTPAuthGate {
  constructor() {
    this.currentScreen = 'signup-choice'; // 'signup-choice', 'signup-email', 'otp-verify', 'password-set', 'login'
    this.email = '';
    this.verificationToken = '';

    // Load saved theme preference
    const savedTheme = localStorage.getItem('otp-theme') || 'light';
    if (savedTheme === 'dark') {
      document.documentElement.classList.add('dark');
    }

    this.setupDOM();
    this.attachEventListeners();
  }

  setupDOM() {
    // Create OTP auth container
    const container = document.createElement('div');
    container.id = 'otp-auth-gate';
    container.innerHTML = `
      <!-- Screen: Choose signup or login -->
      <div id="otp-choice-screen" class="otp-screen otp-screen--active">
        <div class="otp-card">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px;">
            <div class="otp-brand">
              <div class="otp-brand-mark">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                  <circle cx="18" cy="8" r="1.5" fill="currentColor"></circle>
                </svg>
              </div>
              <div>
                <div class="otp-brand-name">RAG</div>
                <div class="otp-brand-sub">Document Assistant</div>
              </div>
            </div>
            <button id="btn-theme-toggle" style="background: none; border: none; cursor: pointer; padding: 8px; display: flex; align-items: center; justify-content: center; color: #999; transition: color 0.2s;" title="Toggle dark mode">
              <svg class="theme-sun" width="20" height="20" fill="currentColor" viewBox="0 0 20 20" style="display: none;">
                <path fill-rule="evenodd" d="M10 2a1 1 0 011 1v2a1 1 0 11-2 0V3a1 1 0 011-1zM4.22 4.22a1 1 0 011.415 0l1.414 1.414a1 1 0 01-1.414 1.414L4.22 5.636a1 1 0 010-1.414zm11.313 0a1 1 0 010 1.414l-1.414 1.414a1 1 0 01-1.414-1.414l1.414-1.414a1 1 0 011.414 0zM10 7a3 3 0 100 6 3 3 0 000-6zm-7 3a1 1 0 11-2 0 1 1 0 012 0zm14 0a1 1 0 11-2 0 1 1 0 012 0zm-9.9 9.9a1 1 0 011.414-1.414l1.414 1.414a1 1 0 01-1.414 1.414l-1.414-1.414zM4.22 15.78a1 1 0 011.414 1.414l-1.414 1.414a1 1 0 01-1.414-1.414l1.414-1.414zm11.313 0l1.414 1.414a1 1 0 01-1.414 1.414l-1.414-1.414a1 1 0 011.414-1.414zM10 18a1 1 0 011-1h2a1 1 0 110 2h-2a1 1 0 01-1-1z" clip-rule="evenodd"></path>
              </svg>
              <svg class="theme-moon" width="20" height="20" fill="currentColor" viewBox="0 0 20 20">
                <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z"></path>
              </svg>
            </button>
          </div>
          
          <div class="otp-buttons">
            <button id="btn-signup-email" class="otp-btn otp-btn--primary">
              Sign Up
            </button>
            <button id="btn-login-email" class="otp-btn otp-btn--secondary">
              Sign In
            </button>
          </div>

          <div class="otp-footer">
            Government of Chhattisgarh · Restricted Access
          </div>
        </div>
      </div>

      <!-- Screen: Enter email for signup -->
      <div id="otp-email-screen" class="otp-screen">
        <div class="otp-card">
          <div class="otp-back">
            <button id="btn-back-to-choice" class="otp-back-btn">← Back</button>
          </div>

          <h2 class="otp-title">Create Account</h2>
          <p class="otp-subtitle">Enter your email address</p>

          <form id="otp-email-form" autocomplete="off" novalidate>
            <div class="otp-field">
              <label for="otp-email-input">Email</label>
              <input 
                id="otp-email-input"
                type="email"
                placeholder="your@email.com"
                autocomplete="email"
                spellcheck="false"
              />
            </div>

            <div id="otp-email-error" class="otp-error hidden"></div>

            <button id="btn-send-otp" type="submit" class="otp-btn otp-btn--primary otp-btn--block">
              <span class="otp-btn-text">Send OTP</span>
              <span class="otp-btn-spinner hidden">
                <span class="otp-dot"></span>
                <span class="otp-dot"></span>
                <span class="otp-dot"></span>
              </span>
            </button>
          </form>

          <div class="otp-footer">
            Government of Chhattisgarh · Restricted Access
          </div>
        </div>
      </div>

      <!-- Screen: Enter OTP -->
      <div id="otp-verify-screen" class="otp-screen">
        <div class="otp-card">
          <div class="otp-back">
            <button id="btn-back-to-email" class="otp-back-btn">← Back</button>
          </div>

          <h2 class="otp-title">Verify Email</h2>
          <p class="otp-subtitle" id="otp-email-display">Sent to: —</p>

          <form id="otp-verify-form" autocomplete="off" novalidate>
            <div class="otp-field">
              <label for="otp-code-input">6-Digit OTP</label>
              <input 
                id="otp-code-input"
                type="text"
                placeholder="000000"
                inputmode="numeric"
                maxlength="6"
                autocomplete="off"
                spellcheck="false"
              />
            </div>

            <div id="otp-verify-error" class="otp-error hidden"></div>

            <button id="btn-verify-otp" type="submit" class="otp-btn otp-btn--primary otp-btn--block">
              <span class="otp-btn-text">Verify OTP</span>
              <span class="otp-btn-spinner hidden">
                <span class="otp-dot"></span>
                <span class="otp-dot"></span>
                <span class="otp-dot"></span>
              </span>
            </button>

            <p class="otp-resend-text">
              Didn't receive OTP? 
              <button id="btn-resend-otp" type="button" class="otp-link-btn">Resend</button>
            </p>
          </form>

          <div class="otp-footer">
            Government of Chhattisgarh · Restricted Access
          </div>
        </div>
      </div>

      <!-- Screen: Set password -->
      <div id="otp-password-screen" class="otp-screen">
        <div class="otp-card">
          <div class="otp-back">
            <button id="btn-back-to-verify" class="otp-back-btn">← Back</button>
          </div>
          <h2 class="otp-title">Set Password</h2>
          <p class="otp-subtitle">Create a strong password for your account</p>

          <form id="otp-password-form" autocomplete="off" novalidate>
            <div class="otp-field">
              <label for="otp-password-input">Password</label>
              <input 
                id="otp-password-input"
                type="password"
                minlength="12"
                maxlength="128"
                placeholder="At least 12 characters"
                autocomplete="new-password"
              />
              <small class="otp-field-hint">Minimum 12 characters with a letter and number</small>
            </div>

            <div class="otp-field">
              <label for="otp-confirm-input">Confirm Password</label>
              <input 
                id="otp-confirm-input"
                type="password"
                placeholder="Re-enter password"
                autocomplete="new-password"
              />
            </div>

            <div id="otp-password-error" class="otp-error hidden"></div>

            <button id="btn-register" type="submit" class="otp-btn otp-btn--primary otp-btn--block">
              <span class="otp-btn-text">Create Account</span>
              <span class="otp-btn-spinner hidden">
                <span class="otp-dot"></span>
                <span class="otp-dot"></span>
                <span class="otp-dot"></span>
              </span>
            </button>
          </form>

          <div class="otp-footer">
            Government of Chhattisgarh · Restricted Access
          </div>
        </div>
      </div>

      <!-- Screen: Login with email and password -->
      <div id="otp-login-screen" class="otp-screen">
        <div class="otp-card">
          <div class="otp-back">
            <button id="btn-back-to-choice-login" class="otp-back-btn">← Back</button>
          </div>

          <h2 class="otp-title">Sign In</h2>
          <p class="otp-subtitle">Enter your credentials</p>

          <form id="otp-login-form" autocomplete="off" novalidate>
            <div class="otp-field">
              <label for="otp-login-email">Email</label>
              <input 
                id="otp-login-email"
                type="email"
                placeholder="your@email.com"
                autocomplete="email"
                spellcheck="false"
              />
            </div>

            <div class="otp-field">
              <label for="otp-login-password">Password</label>
              <input 
                id="otp-login-password"
                type="password"
                placeholder="Enter password"
                autocomplete="current-password"
              />
            </div>

            <div id="otp-login-error" class="otp-error hidden"></div>

            <button id="btn-login" type="submit" class="otp-btn otp-btn--primary otp-btn--block">
              <span class="otp-btn-text">Sign In</span>
              <span class="otp-btn-spinner hidden">
                <span class="otp-dot"></span>
                <span class="otp-dot"></span>
                <span class="otp-dot"></span>
              </span>
            </button>
          </form>

          <div class="otp-footer">
            Government of Chhattisgarh · Restricted Access
          </div>
        </div>
      </div>
    `;

    document.body.insertBefore(container, document.body.firstChild);
    this.el = container;
  }

  attachEventListeners() {
    // Theme toggle
    const themeToggleBtn = document.getElementById('btn-theme-toggle');
    if (themeToggleBtn) {
      themeToggleBtn.addEventListener('click', () => {
        const isDark = document.documentElement.classList.contains('dark');
        if (isDark) {
          document.documentElement.classList.remove('dark');
          localStorage.setItem('otp-theme', 'light');
        } else {
          document.documentElement.classList.add('dark');
          localStorage.setItem('otp-theme', 'dark');
        }
        this.updateThemeIcons();
      });
      this.updateThemeIcons();
    }

    // Choice screen
    document.getElementById('btn-signup-email').addEventListener('click', () => this.showScreen('email'));
    document.getElementById('btn-login-email').addEventListener('click', () => this.showScreen('login'));

    // Email screen
    document.getElementById('btn-back-to-choice').addEventListener('click', () => this.showScreen('choice'));
    document.getElementById('otp-email-form').addEventListener('submit', (e) => this.handleSendOTP(e));

    // OTP verify screen
    document.getElementById('btn-back-to-email').addEventListener('click', () => this.showScreen('email'));
    document.getElementById('otp-code-input').addEventListener('input', (e) => this.filterNumericInput(e));
    document.getElementById('otp-verify-form').addEventListener('submit', (e) => this.handleVerifyOTP(e));
    document.getElementById('btn-resend-otp').addEventListener('click', (e) => this.handleResendOTP(e));

    // Password screen
    document.getElementById('btn-back-to-verify').addEventListener('click', () => this.showScreen('verify'));
    document.getElementById('otp-password-form').addEventListener('submit', (e) => this.handleRegister(e));

    // Login screen
    document.getElementById('btn-back-to-choice-login').addEventListener('click', () => this.showScreen('choice'));
    document.getElementById('otp-login-form').addEventListener('submit', (e) => this.handleLogin(e));
  }

  filterNumericInput(e) {
    e.target.value = e.target.value.replace(/\D/g, '');
  }

  updateThemeIcons() {
    const isDark = document.documentElement.classList.contains('dark');
    const sunIcon = document.querySelector('.theme-sun');
    const moonIcon = document.querySelector('.theme-moon');
    if (sunIcon && moonIcon) {
      if (isDark) {
        sunIcon.style.display = 'block';
        moonIcon.style.display = 'none';
      } else {
        sunIcon.style.display = 'none';
        moonIcon.style.display = 'block';
      }
    }
  }

  showScreen(screen) {
    // Hide all screens
    document.querySelectorAll('.otp-screen').forEach(el => el.classList.remove('otp-screen--active'));

    // Show requested screen
    switch (screen) {
      case 'choice':
        document.getElementById('otp-choice-screen').classList.add('otp-screen--active');
        this.currentScreen = 'choice';
        break;
      case 'email':
        document.getElementById('otp-email-screen').classList.add('otp-screen--active');
        setTimeout(() => document.getElementById('otp-email-input').focus(), 100);
        this.currentScreen = 'email';
        break;
      case 'verify':
        document.getElementById('otp-verify-screen').classList.add('otp-screen--active');
        document.getElementById('otp-email-display').textContent = `Sent to: ${this.email}`;
        setTimeout(() => document.getElementById('otp-code-input').focus(), 100);
        this.currentScreen = 'verify';
        break;
      case 'password':
        document.getElementById('otp-password-screen').classList.add('otp-screen--active');
        setTimeout(() => document.getElementById('otp-password-input').focus(), 100);
        this.currentScreen = 'password';
        break;
      case 'login':
        document.getElementById('otp-login-screen').classList.add('otp-screen--active');
        setTimeout(() => document.getElementById('otp-login-email').focus(), 100);
        this.currentScreen = 'login';
        break;
    }
  }

  setButtonLoading(buttonId, isLoading) {
    const btn = document.getElementById(buttonId);
    const text = btn.querySelector('.otp-btn-text');
    const spinner = btn.querySelector('.otp-btn-spinner');

    btn.disabled = isLoading;
    if (isLoading) {
      text.classList.add('hidden');
      spinner.classList.remove('hidden');
    } else {
      text.classList.remove('hidden');
      spinner.classList.add('hidden');
    }
  }

  showError(elementId, message) {
    const el = document.getElementById(elementId);
    el.textContent = message;
    el.classList.remove('hidden');
  }

  hideError(elementId) {
    const el = document.getElementById(elementId);
    el.classList.add('hidden');
  }

  async handleSendOTP(e) {
    e.preventDefault();
    this.hideError('otp-email-error');

    const email = document.getElementById('otp-email-input').value.trim();
    if (!email) {
      this.showError('otp-email-error', 'Please enter an email');
      return;
    }

    this.setButtonLoading('btn-send-otp', true);

    try {
      const res = await fetch('/otp-auth/send-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });

      const data = await res.json();

      if (data.success) {
        this.email = email;
        this.showScreen('verify');
      } else {
        this.showError('otp-email-error', data.error || 'Failed to send OTP');
      }
    } catch (err) {
      this.showError('otp-email-error', 'Network error: ' + err.message);
    } finally {
      this.setButtonLoading('btn-send-otp', false);
    }
  }

  async handleVerifyOTP(e) {
    e.preventDefault();
    this.hideError('otp-verify-error');

    const otp = document.getElementById('otp-code-input').value.trim();
    if (!otp || otp.length !== 6) {
      this.showError('otp-verify-error', 'Please enter a valid 6-digit OTP');
      return;
    }

    this.setButtonLoading('btn-verify-otp', true);

    try {
      const res = await fetch('/otp-auth/verify-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: this.email, otp }),
      });

      const data = await res.json();

      if (data.success) {
        this.verificationToken = data.verificationToken;
        this.showScreen('password');
      } else {
        this.showError('otp-verify-error', data.error || 'OTP verification failed');
      }
    } catch (err) {
      this.showError('otp-verify-error', 'Network error: ' + err.message);
    } finally {
      this.setButtonLoading('btn-verify-otp', false);
    }
  }

  async handleResendOTP(e) {
    e.preventDefault();
    this.hideError('otp-verify-error');
    this.setButtonLoading('btn-resend-otp', true);

    try {
      const res = await fetch('/otp-auth/send-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: this.email }),
      });

      const data = await res.json();

      if (data.success) {
        this.showError('otp-verify-error', 'OTP resent successfully');
        setTimeout(() => this.hideError('otp-verify-error'), 3000);
      } else {
        this.showError('otp-verify-error', data.error || 'Failed to resend OTP');
      }
    } catch (err) {
      this.showError('otp-verify-error', 'Network error: ' + err.message);
    } finally {
      this.setButtonLoading('btn-resend-otp', false);
    }
  }

  async handleRegister(e) {
    e.preventDefault();
    this.hideError('otp-password-error');

    const password = document.getElementById('otp-password-input').value;
    const confirmPassword = document.getElementById('otp-confirm-input').value;

    if (!password || password.length < 12) {
      this.showError('otp-password-error', 'Password must be at least 12 characters');
      return;
    }

    if (!/[a-z]/i.test(password) || !/\d/.test(password)) {
      this.showError('otp-password-error', 'Password must contain at least one letter and one number');
      return;
    }

    if (password !== confirmPassword) {
      this.showError('otp-password-error', 'Passwords do not match');
      return;
    }

    this.setButtonLoading('btn-register', true);

    try {
      const res = await fetch('/otp-auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: this.email,
          password,
          confirmPassword,
          verificationToken: this.verificationToken,
        }),
      });

      const data = await res.json();

      if (data.success) {
        this.showError('otp-password-error', 'Account created successfully! Redirecting to login...');
        document.getElementById('otp-password-error').classList.remove('otp-error');
        document.getElementById('otp-password-error').classList.add('otp-success');
        setTimeout(() => {
          this.showScreen('login');
          document.getElementById('otp-password-error').classList.remove('otp-success');
          document.getElementById('otp-password-error').classList.add('otp-error');
        }, 2000);
      } else {
        this.showError('otp-password-error', data.error || 'Registration failed');
      }
    } catch (err) {
      this.showError('otp-password-error', 'Network error: ' + err.message);
    } finally {
      this.setButtonLoading('btn-register', false);
    }
  }

  async handleLogin(e) {
    e.preventDefault();
    this.hideError('otp-login-error');

    const email = document.getElementById('otp-login-email').value.trim();
    const password = document.getElementById('otp-login-password').value;

    if (!email || !password) {
      this.showError('otp-login-error', 'Please enter email and password');
      return;
    }

    this.setButtonLoading('btn-login', true);

    try {
      const res = await fetch('/otp-auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      const data = await res.json();

      if (data.success) {
        // Preserve user info for the UI; the actual auth state lives in the httpOnly cookie.
        if (data.user) {
          sessionStorage.setItem(USER_KEY, JSON.stringify(data.user));
          sessionStorage.setItem(USER_EMAIL_KEY, data.user.email || email);
        }

        this.hide();
        window.location.href = '/select';
      } else {
        this.showError('otp-login-error', data.error || 'Login failed');
      }
    } catch (err) {
      this.showError('otp-login-error', 'Network error: ' + err.message);
    } finally {
      this.setButtonLoading('btn-login', false);
    }
  }

  show() {
    this.el.style.display = '';
    this.showScreen('choice');
  }

  hide() {
    this.el.style.display = 'none';
  }
}

// ── Global OTP Auth Gate instance ────────────────────────────────────────────
let otpAuthGate = null;

function initializeOTPAuthGate() {
  if (!otpAuthGate) {
    otpAuthGate = new OTPAuthGate();
  }
  otpAuthGate.show();
}

function hideOTPAuthGate() {
  if (otpAuthGate) {
    otpAuthGate.hide();
  }
}

// Expose to window so modules can access it
window.initializeOTPAuthGate = initializeOTPAuthGate;
window.hideOTPAuthGate = hideOTPAuthGate;

console.log('[otp-auth] OTP auth gate functions exposed to window');
console.log('[otp-auth] window.initializeOTPAuthGate =', typeof window.initializeOTPAuthGate);

// Auto-initialize on page load if OTP auth is not yet set up
document.addEventListener('DOMContentLoaded', () => {
  // Check if user is already authenticated in session
  if (!sessionStorage.getItem(TOKEN_KEY) && typeof initializeOTPAuthGate === 'function') {
    // Don't auto-show yet - let boot() function decide
  }
});
