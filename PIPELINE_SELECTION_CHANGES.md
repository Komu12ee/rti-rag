# Pipeline Selection Architecture - Implementation Summary

## Overview
The application now supports multiple RAG pipelines (CHiPS, Finance/GAD) with a unified selection interface. Users log in once, then select which pipeline to use.

## Changes Made

### 1. **New File: `/nodejs/utils/pipelines.js`**
   - **Purpose**: Centralized pipeline management and process spawning
   - **Key Features**:
     - `launchPipeline(pipelineName)` - Spawns Flask backend for selected pipeline
     - Process tracking with `Map` to prevent duplicate spawns
     - Health check polling (5-second timeout)
     - Environment variable setup: `FLASK_PORT`, `MKL_THREADING_LAYER`, `NUMEXPR_MAX_THREADS`
   - **Constants**:
     - `CHIPS_APP_PATH` → `CHiPS/05_webui/app.py` (port 5001)
     - `FINANCE_APP_PATH` → `CHiPS/04_embeddings_and_kg/scripts/finance_rag.py` (port 5002)

### 2. **New File: `/nodejs/routes/select.js`**
   - **Route: GET /select**
     - Protected by JWT verification
     - Renders pipeline selection page with two cards (CHiPS, Finance/GAD)
     - Shows user email and logout link
   - **Route: POST /select/launch**
     - Accepts `{ pipeline: "chips" | "finance" }`
     - Spawns the pipeline backend in background
     - Sets `active_pipeline` cookie for proxy routing
     - Returns `{ success: true, redirectUrl: "/index.html" }`

### 3. **Updated: `/nodejs/server.js`**
   - **Added imports**: `{ spawn } from child_process`, `killAllPipelines` from `./utils/pipelines`, `PORTS` from `./utils/pipelines`
   - **Added `/select` routes** with middleware for JSON parsing
   - **Replaced static API proxy** with dynamic proxy that routes to correct Flask backend based on `active_pipeline` cookie
   - **Dynamic proxy logic**:
     - Middleware reads `active_pipeline` cookie (defaults to 'chips')
     - Determines target Flask port from `PORTS` map
     - Routes all `/api` requests to the active pipeline's backend
   - **Graceful shutdown**: Now also calls `killAllPipelines()` on SIGTERM/SIGINT

### 4. **Updated: `/app.py`**
   - **Flask port configuration**: Now reads `FLASK_PORT` environment variable
     - Default: 5000 (for backward compatibility)
     - Can be overridden per-pipeline (5001 for CHiPS, 5002 for Finance)
   - **No other changes** to Flask logic or API endpoints

### 5. **Updated: `/nodejs/public/app.js`**
   - **Modified login redirect**: After successful login, redirects to `/select` instead of showing app directly
   - **Modified logout**: Now goes to `/select` instead of showing login screen
   - **Added "Back to selection" button**:
     - Button ID: `btn-back-select`
     - Location: User bar in sidebar (next to logout)
     - Navigates back to `/select` page
   - **New UI element reference**: `btnBackSelect` in `ui` object
   - **Boot logic**: Checks if token exists and routes accordingly

### 6. **Updated: `/nodejs/public/index.html`**
   - **Added back button**: `<button id="btn-back-select" title="Back to pipeline selection">⬅</button>`
   - Location: User bar, next to logout button
   - Styled consistently with logout button

## User Flow

### Login Path
1. User visits `http://localhost:3000/`
2. Sees OTP/login screen (unchanged)
3. Logs in successfully
4. **Redirected to `/select`** (NEW)
5. Sees pipeline selection page with two cards

### Pipeline Selection Path
1. On `/select` page, user clicks "Launch Pipeline" for CHiPS or Finance
2. POST request sent to `/select/launch` with selected pipeline
3. Express server:
   - Spawns Flask backend for that pipeline (in background)
   - Sets `active_pipeline` cookie
   - Returns redirect to `/index.html`
4. Browser redirects to `/index.html`
5. App loads, all `/api` requests proxy to the selected Flask backend
6. User sees CHiPS RAG interface

### Navigation Within Pipeline
- **Back to Selection**: Click ⬅ button in top-left user bar
- **Logout**: Click ↩ button in top-left user bar (logs out and returns to login)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                 Express.js @ :3000                      │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Static Pages (HTML/CSS/JS)                      │   │
│  │  - /select (pipeline selection)                  │   │
│  │  - /index.html (RAG UI)                          │   │
│  └──────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Authentication (OTP)                            │   │
│  │  - POST /otp-auth/login                          │   │
│  │  - POST /otp-auth/register                       │   │
│  │  - Validates JWT tokens                          │   │
│  └──────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Dynamic API Proxy (Routes based on cookie)      │   │
│  │  - GET /api/* → Flask on port 5001/5002/...      │   │
│  │  - Reads active_pipeline cookie                  │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
         ↓                          ↓
    ┌────────────┐            ┌────────────┐
    │   Flask    │            │   Flask    │
    │   CHiPS    │            │  Finance   │
    │   :5001    │            │   :5002    │
    └────────────┘            └────────────┘
         ↓                          ↓
    ┌────────────┐            ┌────────────┐
    │  RAG API   │            │  RAG API   │
    │  Qdrant    │            │  Qdrant    │
    └────────────┘            └────────────┘
```

## Configuration

### Environment Variables
- `FLASK_PORT` - Port Flask runs on (set per-pipeline)
- `PYTHONIOENCODING=utf-8` - Set by pipeline manager
- `MKL_THREADING_LAYER=GNU` - BLAS threading workaround
- `NUMEXPR_MAX_THREADS=1` - Numpy threading limit

### Pipeline Ports
- **CHiPS RAG**: 5001 (set in `/nodejs/utils/pipelines.js`)
- **Finance/GAD RAG**: 5002 (set in `/nodejs/utils/pipelines.js`)

## Missing Components (TODO)

### 1. **Finance RAG App**
   - File: `CHiPS/04_embeddings_and_kg/scripts/finance_rag.py`
   - Status: **Stub only** - returns error "Finance RAG not yet implemented"
   - Needed: Full Flask app for finance/GAD document RAG pipeline
   - Template: Can copy structure from existing CHiPS `app.py`

### 2. **Flask Port Binding**
   - Current: Each pipeline gets its own port via `FLASK_PORT` env var
   - Note: Must listen on `0.0.0.0:PORT` to be reachable from Express proxy

## Testing Checklist

- [ ] User can log in and reach `/select`
- [ ] Both pipeline cards are visible
- [ ] Clicking "Launch Pipeline" on CHiPS works
- [ ] CHiPS RAG UI loads and functions
- [ ] "Back to selection" (⬅) button works
- [ ] Can switch between pipelines
- [ ] Logout returns to login screen
- [ ] Flask processes spawn/kill correctly
- [ ] Finance stub shows appropriate error message

## Known Limitations

1. **No concurrent pipeline running**: Only one pipeline can be active at a time (by design)
2. **Cookie-based pipeline selection**: Uses HTTP-only cookie; not ideal for multi-tab scenarios
3. **Process spawning in Node**: Child processes might not survive server restart with PM2 (workaround: add to ecosystem.config.js)
4. **No pipeline health UI**: Selection page doesn't show which pipelines are available; just launches

## Future Improvements

1. Use Redis for session-based pipeline tracking (scales better)
2. Pre-spawn all pipelines on startup (faster switching)
3. WebSocket updates for pipeline launch status
4. Per-pipeline authentication/permissions
5. Pipeline resource limits (CPU, memory)
