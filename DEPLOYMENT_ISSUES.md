# Deployment Readiness Issues

This read-only deployment audit found 35 issues: 6 Critical, 16 High, 11 Medium, and 2 Low. Verdict: not safe to deploy as-is on the CG Data Center VM; several issues can block access on a private-IP Linux VM, expose unauthenticated APIs, or fail on a clean offline/restricted deployment.

## Blocking Issues

| ID | File / Location | Issue | Why it matters here | Suggested fix |
|---|---|---|---|---|
| B-01 | `FG/04_embeddings_and_kg/scripts/rag_pipeline.py` committed `HEAD:108` | Real-looking Sarvam API key exists in committed history as a commented fallback. | A government VM deployment should not start from a repo containing exposed credentials; the key must be treated as compromised. | Rotate the key and purge it from git history. |
| B-02 | `FG/05_webui/.env:5,18-19,22` | Local `.env` contains PostgreSQL password and real-looking Sarvam API config. | If copied to the VM or backups, secrets leak; this also encourages manual secret handling. | Keep secrets only in deployment-provided environment variables and provide a redacted example file. |
| B-03 | `FG/05_webui/app.py:46`; `FG/05_webui/services/postgres_db.py:16-22`; `FG/05_webui/services/llm_provider.py:113-123` | Required Flask/Postgres/LLM environment variables are not captured in a checked-in Python env example. | A clean VM can fail at startup or first query because required config is tribal knowledge. | Document all required env vars for Flask, Postgres, Sarvam/Ollama, and Qdrant. |
| B-04 | `selection/server/utils/pipelines.js:245,273`; `selection/routes/select.js:250-251` | Launcher redirects browser users to `http://localhost:<pipelinePort>`. | On a private-IP VM, `localhost` points to the user's machine, not the VM. | Return relative URLs or an env-configured VM/private-IP/reverse-proxy base URL. |
| B-05 | `FG/05_webui/nodejs/server.js:16` | CORS allows only `http://localhost:3000`. | Private-IP access such as `http://10.x.x.x:3000` will not match. | Make allowed origins environment-driven and include the VM/proxy origin. |
| B-06 | `FG/05_webui/.env:9,22`; `FG/05_webui/services/llm_provider.py:164-170` | Runtime LLM config uses Sarvam over public internet. | The CG Data Center VM may have restricted outbound access, so answer generation can fail. | Confirm outbound proxy/allowlist or deploy a local model path such as Ollama. |
| B-07 | `FG/05_webui/services/postgres_db.py:7`; `requirements.txt` | App imports `psycopg`, but root requirements do not include it. | A clean VM using `pip install -r requirements.txt` can fail importing the Flask app. | Add the exact PostgreSQL driver dependency to deployment requirements. |
| B-08 | `requirements.txt:10-17,56-74,81-86,116-140` | Python dependencies are mostly range-pinned, with no production lockfile or hashes. | Restricted PyPI access or resolver drift can break deployment or produce a different runtime. | Create locked production requirements and an offline wheelhouse. |
| B-09 | `requirements.txt:57`; `FG/04_embeddings_and_kg/scripts/rag_pipeline.py:193,206` | spaCy/Hugging Face/BGE models may download on install or first run. | First request can fail or hang on a VM without internet access. | Prefetch/cache models and document the restore path. |
| B-10 | `FG/05_webui/app.py:1822` | Flask runs through `app.run(...)`, not a production WSGI server. | The built-in Flask server is not a production service manager for VM deployment. | Run behind gunicorn/waitress/uwsgi or equivalent. |
| B-11 | `selection/server/utils/pipelines.js:9` | Default Python executable is Windows-only `.venv\Scripts\python.exe`. | Linux VM pipeline launch fails unless `PYTHON_EXE` is manually set. | Use an env-required Python path or POSIX-safe default. |
| B-12 | `selection/server/utils/pipelines.js:19-24,58-67`; `selection/server.js:94` | Launcher references unavailable `CHiPS` and `FG-2`; default auto-launch includes `fg2`. | This checkout only clearly contains `FG`, so default launch can fail on the VM. | Remove unavailable pipelines or gate launch by config/path existence. |
| B-13 | `.gitignore:41-44`; `FG/05_webui/app.py:109-122`; `FG/04_embeddings_and_kg/scripts/rag_pipeline.py:81-85` | Embedded Qdrant state is ignored and clean clone has no collections. | `/api/init` fails or the app starts with no searchable corpus. | Restore Qdrant backup or run indexing as a deployment step. |
| B-14 | `selection/data/auth.db`; `selection/data/auth.db-wal`; `selection/data/auth.db-shm`; `selection/utils/db-utils.js:11` | Development SQLite auth DB files are tracked and used by default. | Deployment may ship dev auth state, OTPs, or user hashes. | Remove DB files from repo and initialize per environment. |
| B-15 | `FG/05_webui/nodejs/server.js:79-81`; `FG/05_webui/app.py:256-263` | Pipeline UI/API proxy has no JWT guard and Flask has dummy login. | If ports `3002` or `5000` are reachable, auth is bypassed. | Enforce auth at proxy/backend or expose only the protected selection/reverse-proxy route. |
| B-16 | `selection/routes/select.js:11-12`; `selection/routes/otp-auth.js:95-100,127,228-233` | Auth/session is forgeable: cookie is just an email and verification token is unsigned base64 JSON. | Any user who can reach the app can forge identity/session data. | Use signed server-side sessions or JWTs with secret, expiry, and validation. |
| B-17 | `selection/routes/otp-auth.js:40` | OTP values are logged in plaintext. | VM logs can expose live login codes to operators or anyone with log access. | Never log OTP values. |
| B-18 | `selection/routes/otp-auth.js:24,71,202`; `FG/05_webui/app.py:1066,1256` | No implemented rate limiting for OTP/login/query/PIO analysis. | A shared private network can still brute-force OTPs or exhaust LLM/CPU resources. | Add per-IP/user rate limits. |
| B-19 | `selection/server/utils/pipelines.js:11-17,71-83` | Pipeline ports are hardcoded. | Data-center reverse proxy or port allocation changes require code edits. | Move ports to deployment config/env vars. |
| B-20 | `README.md:199-202`; `FG/docs/SETUP_INSTRUCTIONS.md:41,93` | Docs use `05_webui/app.py`, but the actual app path is `FG/05_webui/app.py`. | A VM operator following the docs will start from the wrong path. | Correct deployment documentation. |
| B-21 | `FG/docs/SETUP_INSTRUCTIONS.md:29-41,83-95` | Dockerfile/systemd are examples, not checked-in deployment artifacts. | Manual deployment has no reproducible service definition. | Commit target-specific deployment files or explicitly document manual service setup. |
| B-22 | `.gitignore:11-13,41-44`; `FG/docs/SETUP_INSTRUCTIONS.md:299-314` | No reproducible restore path for ignored `.env`, Qdrant DB, and model/runtime state. | Clean VM setup cannot reproduce the current working app reliably. | Create a deployment runbook covering env, model cache, Qdrant restore/indexing, and startup order. |

## Full Findings

## Environment & Configuration

### ENV-01 - Committed Sarvam credential in repository history
- File/line: `FG/04_embeddings_and_kg/scripts/rag_pipeline.py` committed `HEAD:108`
- Severity: Critical
- Description: A real-looking Sarvam API key exists in a commented fallback value in committed history.
- Why it matters here: The deployment repo itself contains sensitive material; this is not safe for a government VM or shared deployment process.
- Suggested fix: Rotate the key and purge the secret from git history.

### ENV-02 - Local `.env` contains live-looking credentials
- File/line: `FG/05_webui/.env:5,18-19,22`
- Severity: High
- Description: The local `.env` contains a PostgreSQL password and real-looking Sarvam API config.
- Why it matters here: If this file is copied to the VM or backups, credentials leak and remain hard to rotate cleanly.
- Suggested fix: Keep secrets only in VM environment/secret management and provide a redacted `.env.example`.

### ENV-03 - Missing checked-in Python deployment env example
- File/line: `FG/05_webui/app.py:46`; `FG/05_webui/services/postgres_db.py:16-22`; `FG/05_webui/services/llm_provider.py:113-123`
- Severity: High
- Description: Required Flask/Postgres/LLM env vars are not documented in a checked-in Python `.env.example`.
- Why it matters here: A clean VM can start with missing config and fail at import time, initialization, or first query.
- Suggested fix: Document required env vars for Flask, Postgres, Sarvam/Ollama, Qdrant, and production flags.

### ENV-04 - PM2 config defaults to development mode
- File/line: `ecosystem.config.js:18-21`
- Severity: Medium
- Description: PM2 config sets `NODE_ENV=development` and auto-launches `fg,fg2`.
- Why it matters here: Production behavior differs from development, and auto-launch includes an unavailable pipeline.
- Suggested fix: Create a production PM2 config with `NODE_ENV=production` and only deployed pipelines.

## Networking & Binding

### NET-01 - Browser redirect uses localhost pipeline URL
- File/line: `selection/server/utils/pipelines.js:245,273`; `selection/routes/select.js:250-251`
- Severity: Critical
- Description: Pipeline launch returns `http://localhost:<pipelinePort>` to the browser.
- Why it matters here: On a private-IP VM, remote users will be redirected to their own computer, not the VM.
- Suggested fix: Return relative URLs or a configured VM/private-IP/reverse-proxy base URL.

### NET-02 - CORS is hardcoded to localhost
- File/line: `FG/05_webui/nodejs/server.js:16`
- Severity: High
- Description: CORS allows only `http://localhost:3000`.
- Why it matters here: Private-IP access through the VM or reverse proxy will not match this origin.
- Suggested fix: Make allowed origins environment-driven and include the VM/proxy origin.

### NET-03 - Runtime depends on external Sarvam API
- File/line: `FG/05_webui/.env:9,22`; `FG/05_webui/services/llm_provider.py:164-170`
- Severity: High
- Description: Current runtime config uses Sarvam over the public internet.
- Why it matters here: The CG Data Center VM may have restricted outbound internet or a proxy, so generation can fail.
- Suggested fix: Confirm outbound allowlisting/proxy or deploy a local model path such as Ollama.

### NET-04 - Frontend depends on external fonts/CDN
- File/line: `selection/routes/select.js:37`; `selection/public/index.html:8-11`; `FG/05_webui/nodejs/public/index.html:8-11`
- Severity: Medium
- Description: Pages load Tailwind/Google Fonts from public internet.
- Why it matters here: Restricted government networks may block these assets, causing degraded or broken UI.
- Suggested fix: Vendor all required frontend assets locally.

## Build & Dependencies

### BUILD-01 - Missing `psycopg` dependency
- File/line: `FG/05_webui/services/postgres_db.py:7`; `requirements.txt`
- Severity: Critical
- Description: The Flask app imports `psycopg`, but the root requirements file does not include it.
- Why it matters here: A clean VM following the documented install can fail importing the app.
- Suggested fix: Add the exact PostgreSQL driver dependency to deployment requirements.

### BUILD-02 - Python dependencies are not production locked
- File/line: `requirements.txt:10-17,56-74,81-86,116-140`
- Severity: High
- Description: Most Python dependencies use `>=` ranges and there is no lockfile or hash-pinned production set.
- Why it matters here: Restricted or delayed deployment can resolve different versions or fail on package availability.
- Suggested fix: Create a locked production requirements file and offline wheelhouse.

### BUILD-03 - Model downloads may happen during install or first run
- File/line: `requirements.txt:57`; `FG/04_embeddings_and_kg/scripts/rag_pipeline.py:193,206`
- Severity: High
- Description: spaCy/Hugging Face/BGE model assets may be downloaded dynamically.
- Why it matters here: A private VM may not be able to reach external model registries.
- Suggested fix: Prefetch/cache all models and document how to restore them on the VM.

### BUILD-04 - Native Node dependency may need OS build tooling
- File/line: `selection/package-lock.json:300-308`
- Severity: Medium
- Description: `better-sqlite3` has an install script and native/prebuilt dependency path.
- Why it matters here: Minimal Linux images may lack compiler/build tools or a compatible prebuilt package.
- Suggested fix: Document Node/native build prerequisites or prebuild/test for the target OS.

## Process & Service Management

### PROC-01 - Flask development server is the actual start path
- File/line: `FG/05_webui/app.py:1822`
- Severity: High
- Description: The app starts with Flask `app.run(...)`.
- Why it matters here: This is not a production WSGI service for a VM deployment.
- Suggested fix: Run the Flask app behind a production WSGI server.

### PROC-02 - Linux launch fails without manual Python override
- File/line: `selection/server/utils/pipelines.js:9`
- Severity: High
- Description: Default Python executable is `.venv\Scripts\python.exe`, a Windows path.
- Why it matters here: The CG Data Center VM is Linux, so pipeline launch fails unless `PYTHON_EXE` is set.
- Suggested fix: Require/configure a POSIX Python executable path.

### PROC-03 - Launcher references unavailable pipelines
- File/line: `selection/server/utils/pipelines.js:19-24,58-67`; `selection/server.js:94`
- Severity: High
- Description: Launcher references `CHiPS` and `FG-2`; default auto-launch includes `fg2`, but this checkout only clearly contains `FG`.
- Why it matters here: Startup/auto-launch can fail or produce confusing partial availability.
- Suggested fix: Remove unavailable pipelines or make pipeline registration config/path-driven.

### PROC-04 - Child Flask/Node processes are not supervised independently
- File/line: `selection/server/utils/pipelines.js:151-173,209-228`
- Severity: Medium
- Description: PM2 supervises selection, but launched child services are not restarted on crash.
- Why it matters here: A pipeline process can die while the selection server remains up.
- Suggested fix: Run every service under PM2/systemd or add supervised restart behavior.

## Database & Persistence

### DB-01 - Qdrant state is ignored and not restored by clean clone
- File/line: `.gitignore:41-44`; `FG/05_webui/app.py:109-122`; `FG/04_embeddings_and_kg/scripts/rag_pipeline.py:81-85`
- Severity: High
- Description: Embedded Qdrant database files are ignored; clean clone has no guaranteed collections.
- Why it matters here: `/api/init` fails if configured collections do not exist, or the app has no corpus.
- Suggested fix: Restore Qdrant backup or run the indexing pipeline before go-live.

### DB-02 - Development auth DB files are tracked
- File/line: `selection/data/auth.db`; `selection/data/auth.db-wal`; `selection/data/auth.db-shm`; `selection/utils/db-utils.js:11`
- Severity: High
- Description: SQLite auth DB files are in the repo and used by default.
- Why it matters here: Deployment may carry dev users, OTP data, or hashes into production.
- Suggested fix: Remove DB files from repo and initialize auth DB per environment.

### DB-03 - PostgreSQL config has localhost defaults and no retry/backoff
- File/line: `FG/05_webui/services/postgres_db.py:24-31,43`
- Severity: Medium
- Description: Postgres defaults to localhost/postgres and opens a direct connection without retry/backoff.
- Why it matters here: If the database is remote, delayed, or managed by another service, lookups can fail.
- Suggested fix: Use explicit env config and add startup/request retry handling.

### DB-04 - Embedded Qdrant is process-lock sensitive
- File/line: `FG/04_embeddings_and_kg/scripts/rag_pipeline.py:249-252,271-282`
- Severity: Medium
- Description: Local embedded Qdrant can be accessed by only one process at a time.
- Why it matters here: Multi-worker WSGI or parallel tools can lock the DB and fail retrieval.
- Suggested fix: Use remote Qdrant in production or enforce a single-process model.

## Security

### SEC-01 - Pipeline API can bypass selection auth
- File/line: `FG/05_webui/nodejs/server.js:79-81`; `FG/05_webui/app.py:256-263`
- Severity: Critical
- Description: Pipeline proxy has no JWT guard and Flask has dummy login.
- Why it matters here: If pipeline ports are reachable on the VM network, users can bypass login.
- Suggested fix: Enforce auth on proxy/backend or expose only a protected reverse-proxy route.

### SEC-02 - Session and verification token are forgeable
- File/line: `selection/routes/select.js:11-12`; `selection/routes/otp-auth.js:95-100,127,228-233`
- Severity: Critical
- Description: Session cookie is plain email and verification token is unsigned base64 JSON.
- Why it matters here: Users can forge identity/session state on a reachable private network.
- Suggested fix: Use signed server-side sessions or JWTs with secret, expiry, and validation.

### SEC-03 - OTP is logged in plaintext
- File/line: `selection/routes/otp-auth.js:40`
- Severity: High
- Description: Generated OTP values are printed to logs.
- Why it matters here: Logs on the VM may be visible to operators or support staff.
- Suggested fix: Never log OTP values.

### SEC-04 - No rate limiting on auth and expensive endpoints
- File/line: `selection/routes/otp-auth.js:24,71,202`; `FG/05_webui/app.py:1066,1256`
- Severity: High
- Description: OTP, login, RAG query, and PIO analysis routes have no implemented rate limiting.
- Why it matters here: A shared private network can still brute-force or exhaust CPU/LLM/API quota.
- Suggested fix: Add per-IP/user rate limits.

### SEC-05 - Verbose errors returned to clients
- File/line: `FG/05_webui/app.py:493-500,1240-1250`
- Severity: Medium
- Description: Exception strings are returned in JSON responses.
- Why it matters here: Users can see internal configuration/path/provider failures.
- Suggested fix: Return generic production errors and log details server-side.

### SEC-06 - Scraper disables TLS certificate verification
- File/line: `Scraper/download_pdfs.py:17-18,111-116`
- Severity: Medium
- Description: Download code suppresses TLS warnings and uses `verify=False`.
- Why it matters here: If the scraper is run from the VM, downloads can be intercepted or modified.
- Suggested fix: Verify TLS or configure the data-center CA/proxy certificate.

## Logging & Monitoring

### LOG-01 - Log files have no rotation policy
- File/line: `selection/server/utils/pipelines.js:127,183`; `ecosystem.config.js:16-17`
- Severity: Medium
- Description: Services write local log files with no repo-defined rotation.
- Why it matters here: A small VM disk can fill and take down services.
- Suggested fix: Configure PM2 log rotation or systemd journald limits.

### LOG-02 - Node UI health check is not explicit
- File/line: `FG/05_webui/nodejs/server.js:83-85`
- Severity: Medium
- Description: The Node UI has wildcard SPA fallback but no real JSON `/health`.
- Why it matters here: A load balancer or data-center health check can get a false 200 from HTML fallback.
- Suggested fix: Add an explicit JSON health endpoint.

### LOG-03 - PIO debug output can expose sensitive RTI content
- File/line: `FG/05_webui/.env:30`; `FG/05_webui/services/pio_pipeline.py:1223-1229`
- Severity: Medium
- Description: Debug output is enabled and prints generated advisory previews.
- Why it matters here: RTI content may contain sensitive applicant or case details and can leak to logs.
- Suggested fix: Disable debug report output in production.

## Frontend-Backend Integration

### FBI-01 - Frontend redirects to localhost after pipeline launch
- File/line: `selection/server/utils/pipelines.js:245,273`; `selection/routes/select.js:250-251`
- Severity: Critical
- Description: Launch flow sends the browser to a localhost pipeline URL.
- Why it matters here: Remote private-IP users cannot reach the app because the browser targets their own localhost.
- Suggested fix: Use relative URLs or a configured external/private base URL.

### FBI-02 - Hardcoded pipeline ports
- File/line: `selection/server/utils/pipelines.js:11-17,71-83`
- Severity: High
- Description: Selection, Node UI, and Flask ports are hardcoded.
- Why it matters here: Data-center reverse proxy/port allocation changes require code changes.
- Suggested fix: Make ports environment/config-driven.

### FBI-03 - Main app API calls are relative
- File/line: `FG/05_webui/nodejs/public/app.js:159-190`
- Severity: Low
- Description: The main app correctly uses relative `/api/...` paths.
- Why it matters here: This part should work once the proxy/base URL issue is fixed.
- Suggested fix: Keep API calls relative.

## Documentation & Reproducibility

### DOC-01 - Deployment docs use wrong app path
- File/line: `README.md:199-202`; `FG/docs/SETUP_INSTRUCTIONS.md:41,93`
- Severity: High
- Description: Docs start `05_webui/app.py`, but the actual path is `FG/05_webui/app.py`.
- Why it matters here: Operators following docs on a clean VM will fail to start the app.
- Suggested fix: Correct deployment commands and working directories.

### DOC-02 - Deployment artifacts are examples, not checked-in runtime files
- File/line: `FG/docs/SETUP_INSTRUCTIONS.md:29-41,83-95`
- Severity: High
- Description: Dockerfile and systemd unit are shown as examples to create, not actual files.
- Why it matters here: Manual deployment has no reproducible service definition.
- Suggested fix: Commit target-specific deployment artifacts or clearly document manual setup.

### DOC-03 - No reproducible state restore runbook
- File/line: `.gitignore:11-13,41-44`; `FG/docs/SETUP_INSTRUCTIONS.md:299-314`
- Severity: High
- Description: Ignored `.env`, Qdrant state, model cache, and runtime state are not covered by a concrete restore process.
- Why it matters here: A clean VM cannot reproduce the current working application reliably.
- Suggested fix: Create a deployment runbook for env vars, model cache, Qdrant restore/indexing, and startup order.

### DOC-04 - Selection README does not match current routing
- File/line: `selection/README.md:55-57`; `selection/routes/select.js:306-310`
- Severity: Medium
- Description: README says an `active_pipeline` cookie routes requests, but launch returns URL/port instead.
- Why it matters here: Operators will debug the wrong routing model.
- Suggested fix: Update docs to match current implementation.

## Pre-deployment Checklist

- [ ] Rotate the exposed Sarvam API key and remove it from git history.
- [ ] Remove all real secrets from local `.env` handling and configure VM secrets through environment/secret management.
- [ ] Create a redacted checked-in env example for Flask/Postgres/Sarvam/Ollama/Qdrant.
- [ ] Replace localhost browser redirects with relative or VM/private-IP/reverse-proxy URLs.
- [ ] Configure allowed CORS origins for the VM/private reverse proxy.
- [ ] Verify Sarvam outbound access or deploy a local Ollama/model alternative.
- [ ] Add the missing `psycopg` dependency to production requirements.
- [ ] Produce locked/offline Python dependency artifacts for the VM.
- [ ] Prefetch and restore all required spaCy/Hugging Face/BGE model assets.
- [ ] Run Flask behind a production WSGI server.
- [ ] Configure a Linux-safe Python executable path for pipeline launches.
- [ ] Remove or disable unavailable `CHiPS` and `FG-2` pipeline launch paths.
- [ ] Restore/index Qdrant collections before `/api/init`.
- [ ] Remove tracked SQLite auth DB files and initialize auth DB per environment.
- [ ] Ensure pipeline ports cannot bypass selection auth, or enforce auth on proxy/backend.
- [ ] Replace forgeable session/verification tokens with signed server-side sessions or validated JWTs.
- [ ] Stop logging OTP values.
- [ ] Add rate limiting to OTP, login, query, and PIO analysis endpoints.
- [ ] Move hardcoded service ports into deployment configuration.
- [ ] Correct deployment docs to use `FG/05_webui/app.py`.
- [ ] Commit or provide target-specific service definitions for the VM.
- [ ] Create a full deployment runbook for env vars, model cache, Qdrant restore/indexing, and startup order.
