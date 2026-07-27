# Security Done

Date: 26 July 2026

## Status

Application-level security hardening has been implemented for:

- the Flask RTI/RAG backend;
- the Node.js web proxy;
- PIO and evaluation access;
- the selection and OTP authentication gateway;
- Prometheus metrics access; and
- local authentication data handling.

This document records the controls implemented in the repository. Infrastructure
controls such as TLS certificates, a managed secret store, Redis-backed shared
sessions/rate limits, a WAF, database encryption, backups, and external security
testing must still be configured in the deployment environment.

## Implemented Controls

### Authentication and passwords

- Citizen passwords are stored as PBKDF2-SHA256 hashes with unique random salts.
- PIO accounts with plaintext `password` values are rejected.
- PIO accounts must use `passwordHash`.
- A password-hash helper is available at
  `FG/05_webui/scripts/hash_pio_password.py`.
- New passwords must contain 12-128 characters, at least one letter, and at
  least one number.
- Authentication responses use generic failure messages to reduce account
  enumeration.
- Bearer sessions use cryptographically random tokens and expire automatically.
- Session storage is bounded to prevent unlimited memory growth.

### OTP and selection gateway

- The old forgeable email cookie was replaced with an HMAC-signed, expiring
  session token.
- Email-verification tokens are signed, typed, and expire after ten minutes.
- OTP values are stored as keyed SHA-256 digests instead of plaintext.
- OTP codes are no longer written to application logs.
- OTP verification is one-time and locks after five invalid attempts.
- Production startup requires an authentication signing secret of at least 32
  characters.
- Production session cookies are `HttpOnly`, `Secure`, `SameSite=Strict`, and
  have an explicit lifetime.
- Logout clears the signed session cookie.
- Automatic pipeline launch is disabled by default in production.

### Authorization

- PIO functions require an authenticated PIO role.
- Evaluation functions require the PIO administrator role.
- Role checks are performed by the Node proxy and independently by Flask for
  direct-backend requests.
- Prometheus may access only `/api/evaluation/metrics` using a dedicated
  `METRICS_SERVICE_TOKEN`.
- The metrics service identity cannot access other evaluation, PIO, or query
  routes.

### Rate limiting and resource protection

- Authentication requests are rate limited.
- RAG query and PIO analysis requests are rate limited.
- PDF uploads have a separate hourly limit.
- Evaluation endpoints are rate limited.
- OTP endpoints are rate limited.
- Rejected requests return HTTP 429 with `Retry-After`.
- Flask multipart form memory and total upload sizes are bounded.
- Node JSON request bodies are size limited.
- Rate-limit key storage is bounded to reduce memory-exhaustion risk.

The implemented limiters are suitable for a single process. Multi-instance
production deployments must move counters to Redis or another shared backend.

### Browser and transport protections

- Browser origins are controlled through an explicit allow-list.
- State-changing Flask requests reject unapproved `Origin` values.
- Forwarded client IP headers are ignored unless `TRUST_PROXY_HEADERS=true`.
- Responses include:
  - `Content-Security-Policy`;
  - `X-Content-Type-Options: nosniff`;
  - `X-Frame-Options: DENY`;
  - `Referrer-Policy: no-referrer`;
  - a restrictive `Permissions-Policy`; and
  - no-store caching for authentication and API responses.
- HSTS is configurable and should be enabled only after HTTPS is working.

### Secret and local-data handling

- Real secrets are not included in example environment files.
- `AUTH_TOKEN_SECRET`, `METRICS_SERVICE_TOKEN`, allowed origins, session
  lifetimes, rate limits, trusted-proxy handling, and HSTS are environment
  controlled.
- `FG/05_webui/data/pio_users.json` is no longer tracked by Git.
- `selection/data/auth.db`, `auth.db-shm`, and `auth.db-wal` are no longer
  tracked by Git.
- The local credential/database files remain available on the development
  machine and are covered by `.gitignore`.
- Example PIO accounts now show `passwordHash` instead of plaintext passwords.

## Required Production Configuration

Set these values through the deployment secret/configuration system:

```dotenv
NODE_ENV=production
AUTH_TOKEN_SECRET=<at-least-32-random-characters>
METRICS_SERVICE_TOKEN=<different-at-least-32-character-random-token>
SECURITY_ALLOWED_ORIGINS=https://your-approved-rti-domain.example
TRUST_PROXY_HEADERS=true
ENABLE_HSTS=true
```

`TRUST_PROXY_HEADERS=true` is safe only when the application is reachable
exclusively through a trusted reverse proxy that overwrites forwarded headers.
Enable HSTS only after HTTPS is correctly configured for the production domain.

The Prometheus scrape configuration should send:

```text
Authorization: Bearer <METRICS_SERVICE_TOKEN>
```

to:

```text
GET /api/evaluation/metrics
```

Grafana should read from Prometheus rather than calling Flask directly.

## Verification Completed

- JavaScript syntax checks passed for the updated Node proxy, authentication,
  OTP, database, selection, middleware, and browser files.
- Six Node security/authentication tests passed.
- One SQLite integration test is included and automatically skips when the
  optional `better-sqlite3` dependency is not installed.
- Python compilation passed for the Flask application, rate limiter, and PIO
  password-hash helper.
- The Python rate-limiter smoke test passed.
- `git diff --check` passed.
- A tracked-file scan confirmed that local PIO credentials and OTP database
  files are removed from version tracking.
- A tracked-secret pattern scan found no populated application secret variables
  outside example/documentation files.

## Deployment-Level Work Still Required

The following cannot be completed safely only through repository code:

1. Terminate HTTPS at a hardened reverse proxy and enable HSTS.
2. Store production secrets in a managed secret store and rotate any previously
   exposed credentials.
3. Replace process-local Flask/Node sessions and rate-limit counters with a
   shared Redis or database-backed implementation before horizontal scaling.
4. Configure encrypted PostgreSQL/Qdrant storage, backups, restore testing, and
   retention/deletion policies for uploaded RTI documents.
5. Run the Flask application behind a production WSGI server.
6. Run dependency, SAST, DAST, penetration, and infrastructure security scans
   in CI/staging.
7. Obtain a security review and legal/data-governance approval before handling
   sensitive government or personal information in production.

The repository now provides a substantially safer application baseline, but
production security remains a continuous operational process rather than a
one-time “perfectly secure” state.
