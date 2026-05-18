'use strict';

const express = require('express');
const { launchPipeline, PORTS } = require('../server/utils/pipelines');

const router = express.Router();

/**
 * Check if user has an active session (simple cookie-based check)
 */
function isAuthenticated(req) {
  return !!req.cookies?.chips_rag_session;
}

/**
 * GET /select
 * Pipeline selection page
 * Protected: requires active session
 */
router.get('/', (req, res) => {
  if (!isAuthenticated(req)) {
    // Return JSON if requested as API, otherwise redirect to login
    if (req.accepts('json')) {
      return res.status(401).json({ success: false, error: 'Unauthorized' });
    }
    return res.redirect('/');
  }

  // Send the selection page
  res.setHeader('Content-Type', 'text/html');
  res.send(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>CHiPS-RAG • Select Pipeline</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    * { transition: background-color 0.2s ease, color 0.2s ease, border-color 0.2s ease; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', sans-serif; }
    
    /* Light mode (default) */
    :root {
      --bg-primary: #f9fafb;
      --bg-card: #ffffff;
      --text-primary: #111827;
      --text-secondary: #6b7280;
      --border: #e5e7eb;
      --button-primary: #2563eb;
      --button-hover: #1d4ed8;
    }
    
    /* Dark mode */
    html.dark {
      --bg-primary: #0f172a;
      --bg-card: #1e293b;
      --text-primary: #f1f5f9;
      --text-secondary: #94a3b8;
      --border: #334155;
      --button-primary: #2563eb;
      --button-hover: #1d4ed8;
    }
    
    body {
      background-color: var(--bg-primary);
      color: var(--text-primary);
    }
  </style>
</head>
<body class="min-h-screen transition-colors duration-200">
  <!-- Navbar -->
  <nav class="border-b" style="border-color: var(--border); background-color: var(--bg-card);">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <!-- Wordmark + Tagline -->
      <div class="flex items-baseline gap-2">
        <h1 class="text-2xl font-bold tracking-tight" style="color: var(--text-primary);">CHiPS-RAG</h1>
        <span class="text-sm" style="color: var(--text-secondary);">Intelligent document Q&A</span>
      </div>
      
      <!-- Right section: Email + Dark toggle + Sign out -->
      <div class="flex items-center gap-4">
        <!-- User email pill -->
        <div id="user-pill" class="hidden px-4 py-2 rounded-full border text-sm" style="border-color: var(--border); background-color: var(--bg-primary); color: var(--text-secondary);"></div>
        
        <!-- Dark mode toggle -->
        <button id="theme-toggle" class="p-2 rounded-lg hover:opacity-70 transition-opacity" style="background-color: var(--bg-primary);" title="Toggle dark mode" aria-label="Toggle dark mode">
          <svg class="sun-icon w-5 h-5" fill="currentColor" viewBox="0 0 20 20" style="color: #f59e0b;">
            <path fill-rule="evenodd" d="M10 2a1 1 0 011 1v2a1 1 0 11-2 0V3a1 1 0 011-1zM4.22 4.22a1 1 0 011.415 0l1.414 1.414a1 1 0 01-1.414 1.414L4.22 5.636a1 1 0 010-1.414zm11.313 0a1 1 0 010 1.414l-1.414 1.414a1 1 0 01-1.414-1.414l1.414-1.414a1 1 0 011.414 0zM10 7a3 3 0 100 6 3 3 0 000-6zm-7 3a1 1 0 11-2 0 1 1 0 012 0zm14 0a1 1 0 11-2 0 1 1 0 012 0zm-9.9 9.9a1 1 0 011.414-1.414l1.414 1.414a1 1 0 01-1.414 1.414l-1.414-1.414zM4.22 15.78a1 1 0 011.414 1.414l-1.414 1.414a1 1 0 01-1.414-1.414l1.414-1.414zm11.313 0l1.414 1.414a1 1 0 01-1.414 1.414l-1.414-1.414a1 1 0 011.414-1.414zM10 18a1 1 0 011-1h2a1 1 0 110 2h-2a1 1 0 01-1-1z" clip-rule="evenodd"></path>
          </svg>
          <svg class="moon-icon w-5 h-5 hidden" fill="currentColor" viewBox="0 0 20 20" style="color: #60a5fa;">
            <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z"></path>
          </svg>
        </button>
        
        <!-- Sign out button -->
        <button id="signout-btn" class="text-sm font-medium transition-colors hover:text-red-500" style="color: var(--text-secondary);" title="Sign out">
          Sign out
        </button>
      </div>
    </div>
  </nav>

  <!-- Main content -->
  <main class="max-w-6xl mx-auto px-4 py-12">
    <!-- Pipeline grid -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
      <!-- CHiPS RAG Card -->
      <div class="group rounded-lg border p-6 transition-all duration-200 hover:shadow-md hover:translate-y-[-2px]" style="background-color: var(--bg-card); border-color: var(--border);">
        <!-- Icon -->
        <div class="w-10 h-10 rounded-lg flex items-center justify-center mb-4" style="background-color: rgba(37, 99, 235, 0.1);">
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="stroke: var(--button-primary);">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
          </svg>
        </div>
        
        <!-- Content -->
        <h2 class="text-lg font-bold mb-2" style="color: var(--text-primary);">CHiPS RAG</h2>
        <p class="text-sm mb-6" style="color: var(--text-secondary);">CHiPS document question-answering system</p>
        
        <!-- Button -->
        <button class="launch-btn w-full py-3 px-4 rounded-lg font-medium text-white flex items-center justify-center gap-2 transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2" data-pipeline="chips" style="background-color: var(--button-primary); focus-visible:ring-color: var(--button-primary);">
          <span class="btn-text">Launch Pipeline</span>
          <svg class="w-4 h-4 group-hover:translate-x-0.5 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"></path>
          </svg>
        </button>
        
        <!-- Error message -->
        <div class="error-msg mt-3 text-sm text-red-500 hidden"></div>
      </div>

      <!-- Finance/GAD RAG Card -->
      <div class="group rounded-lg border p-6 transition-all duration-200 hover:shadow-md hover:translate-y-[-2px]" style="background-color: var(--bg-card); border-color: var(--border);">
        <!-- Icon -->
        <div class="w-10 h-10 rounded-lg flex items-center justify-center mb-4" style="background-color: rgba(37, 99, 235, 0.1);">
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="stroke: var(--button-primary);">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path>
          </svg>
        </div>
        
        <!-- Content -->
        <h2 class="text-lg font-bold mb-2" style="color: var(--text-primary);">Finance / GAD RAG</h2>
        <p class="text-sm mb-6" style="color: var(--text-secondary);">Finance and general administration document analysis</p>
        
        <!-- Button -->
        <button class="launch-btn w-full py-3 px-4 rounded-lg font-medium text-white flex items-center justify-center gap-2 transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2" data-pipeline="finance" style="background-color: var(--button-primary); focus-visible:ring-color: var(--button-primary);">
          <span class="btn-text">Launch Pipeline</span>
          <svg class="w-4 h-4 group-hover:translate-x-0.5 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"></path>
          </svg>
        </button>
        
        <!-- Error message -->
        <div class="error-msg mt-3 text-sm text-red-500 hidden"></div>
      </div>

      <!-- Finance/GAD RAG (FG-2) Card -->
      <div class="group rounded-lg border p-6 transition-all duration-200 hover:shadow-md hover:translate-y-[-2px]" style="background-color: var(--bg-card); border-color: var(--border);">
        <!-- Icon -->
        <div class="w-10 h-10 rounded-lg flex items-center justify-center mb-4" style="background-color: rgba(37, 99, 235, 0.1);">
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="stroke: var(--button-primary);">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path>
          </svg>
        </div>
        
        <!-- Content -->
        <h2 class="text-lg font-bold mb-2" style="color: var(--text-primary);">Finance / GAD RAG (FG-2)</h2>
        <p class="text-sm mb-6" style="color: var(--text-secondary);">Alternate Finance pipeline (FG-2 folder)</p>
        
        <!-- Button -->
        <button class="launch-btn w-full py-3 px-4 rounded-lg font-medium text-white flex items-center justify-center gap-2 transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2" data-pipeline="fg2" style="background-color: var(--button-primary); focus-visible:ring-color: var(--button-primary);">
          <span class="btn-text">Launch Pipeline</span>
          <svg class="w-4 h-4 group-hover:translate-x-0.5 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"></path>
          </svg>
        </button>
        
        <!-- Error message -->
        <div class="error-msg mt-3 text-sm text-red-500 hidden"></div>
      </div>
    </div>
  </main>

  <script>
    'use strict';

    const isDarkMode = () => document.documentElement.classList.contains('dark');
    const setDarkMode = (dark) => {
      if (dark) {
        document.documentElement.classList.add('dark');
        localStorage.setItem('theme', 'dark');
      } else {
        document.documentElement.classList.remove('dark');
        localStorage.setItem('theme', 'light');
      }
      updateThemeIcons();
    };
    
    const updateThemeIcons = () => {
      const sunIcon = document.querySelector('.sun-icon');
      const moonIcon = document.querySelector('.moon-icon');
      if (isDarkMode()) {
        sunIcon.classList.add('hidden');
        moonIcon.classList.remove('hidden');
      } else {
        sunIcon.classList.remove('hidden');
        moonIcon.classList.add('hidden');
      }
    };

    // Initialize theme
    const savedTheme = localStorage.getItem('theme') || 'light';
    setDarkMode(savedTheme === 'dark');

    // Theme toggle
    document.getElementById('theme-toggle').addEventListener('click', () => {
      setDarkMode(!isDarkMode());
    });

    // User display
    const userKey = 'chips_rag_user';
    const user = JSON.parse(sessionStorage.getItem(userKey) || 'null');
    const userPill = document.getElementById('user-pill');
    if (user && user.email) {
      userPill.textContent = user.email;
      userPill.classList.remove('hidden');
    }

    // Handle pipeline launch
    document.querySelectorAll('.launch-btn').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        const pipeline = btn.dataset.pipeline;
        const card = btn.closest('.group');
        const errorEl = card.querySelector('.error-msg');
        const btnText = btn.querySelector('.btn-text');

        btn.disabled = true;
        btnText.textContent = 'Launching...';
        errorEl.classList.add('hidden');

        try {
          const res = await fetch('/select/launch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pipeline }),
          });

          const data = await res.json();

          if (data.success && data.url) {
            window.location.href = data.url;
          } else {
            throw new Error(data.error || 'Launch failed');
          }
        } catch (err) {
          errorEl.textContent = \`Error: \${err.message}\`;
          errorEl.classList.remove('hidden');
          btn.disabled = false;
          btnText.textContent = 'Launch Pipeline';
        }
      });
    });

    // Handle sign out
    document.getElementById('signout-btn').addEventListener('click', async (e) => {
      e.preventDefault();
      try {
        await fetch('/otp-auth/logout', { method: 'POST' });
      } catch (_) {}
      sessionStorage.clear();
      document.cookie = 'token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 UTC; SameSite=Strict';
      window.location.href = '/';
    });
  </script>
</body>
</html>`);
});

/**
 * POST /select/launch
 * Launch a pipeline and set it as active for the current session
 * Body: { pipeline: "chips" | "finance" }
 * Response: { success: true, redirectUrl: "/index.html" } or { success: false, error: "..." }
 */
router.post('/launch', (req, res) => {
  if (!isAuthenticated(req)) {
    return res.status(401).json({ success: false, error: 'Unauthorized' });
  }

  const { pipeline } = req.body || {};

  if (!pipeline || typeof pipeline !== 'string') {
    return res.status(400).json({ success: false, error: 'Pipeline name is required' });
  }

  if (!['chips', 'finance', 'fg2'].includes(pipeline)) {
    return res.status(400).json({ success: false, error: 'Unknown pipeline' });
  }

  launchPipeline(pipeline)
    .then((result) => {
      if (!result.success) {
        return res.status(503).json({ success: false, error: result.error || 'Pipeline failed to start' });
      }

      return res.json({
        success: true,
        url: result.url,
        port: PORTS[pipeline],
      });
    })
    .catch((err) => {
      console.error(`[select] Error launching ${pipeline}:`, err.message);
      return res.status(503).json({ success: false, error: 'Pipeline failed to start' });
    });
});

module.exports = router;
