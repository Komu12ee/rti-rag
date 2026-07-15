# Section 4(1)(b) official-web verification

This package adds a bounded, evidence-first public-domain verification step to the existing Flask PIO-advisory flow. It is intended for questions about proactive disclosure under Section 4(1)(b) of the Right to Information Act and for narrowly related tender-publication checks.

The feature is deliberately not a general web-search facility:

- It uses configured adapters and operator-approved official government hosts only.
- It does not call a paid search API or an unrestricted search engine.
- It does not bypass CAPTCHA, login, robots restrictions, or other access controls.
- A tender notice, bid result, contract listing, or work order is not proof that a payment was made.
- A document not being discovered is not proof that the document or underlying event does not exist.
- The output is retrieval evidence for a PIO/user to inspect. It is not a legal finding and does not replace the underlying PIO advisory.

## 1. Repository analysis and runtime flow

### Existing flow before this feature

The Web UI already had the following path:

~~~text
Browser
  -> Express static UI/proxy on :3002
  -> Flask routes in FG/05_webui/app.py on :5000
  -> PIO extraction and legal analysis in services/pio_pipeline.py
  -> advisory response
  -> optional precedent retrieval
~~~

That path could classify an RTI application and produce a PIO advisory from the local corpus, but it did not produce a separate, durable record of which official public-domain sources were checked. A model statement that information was public could therefore not, by itself, be treated as web evidence.

### New additive flow

The Section 4 verifier runs after the request has a query and, where available, structured RTI extraction/legal analysis. It does not replace extraction, local RAG, the advisory, or precedent retrieval.

~~~text
query / RTI extraction / legal analysis
                  |
                  v
        strict trigger detector
          |               |
          | no            | yes
          v               v
SEARCH_NOT_TRIGGERED   query analyser
                          |
                          v
                 approved source registry
                          |
                          v
             safe fetch + source adapters
                          |
                          v
              HTML/PDF text extraction
                          |
                          v
               evidence validation
                          |
                          v
           result merge + SQLite cache/audit
                          |
                          v
        top-level web_verification in PIO result
                          |
                          v
       localized evidence card in the same reply
~~~

The main PIO response includes <code>web_verification</code> as a top-level field. The browser retains that object when it normalizes both the primary streamed response and PDF-upload response. It does not issue a duplicate verification request. A source-unavailable result can be retried independently without regenerating or discarding the advisory.

### Code layout

~~~text
requirements.txt
tests/
  test_section4_*.py
  test_section4_frontend.py
FG/05_webui/
  .env.example
  app.py
  nodejs/public/
    app.js
    style.css
  services/
    section4_web_verification/
      __init__.py
      config.py
      schemas.py
      trigger_detector.py
      query_analyser.py
      security.py
      cache.py
      rate_limiter.py
      extractors.py
      adapters.py
      source_registry.py
      evidence_validator.py
      result_merger.py
      audit.py
      orchestrator.py
      README.md
~~~

Package responsibilities:

| Module | Responsibility |
| --- | --- |
| <code>config.py</code> | Parse and validate all <code>SECTION4_*</code> settings. |
| <code>schemas.py</code> | Canonical status, trigger, source, evidence, and result structures. |
| <code>trigger_detector.py</code> | Apply the strict Section 4/tender trigger contract. |
| <code>query_analyser.py</code> | Normalize organisation, subject, sub-clause, entities, and requested fields from the supplied request context. |
| <code>security.py</code> | Enforce scheme/host/redirect/network/content safety before and during every fetch. |
| <code>cache.py</code> | Initialize and use the local SQLite cache. |
| <code>rate_limiter.py</code> | Apply per-host spacing and circuit-breaker state. |
| <code>extractors.py</code> | Extract bounded text and metadata from approved HTML/PDF responses. |
| <code>adapters.py</code> | Implement source-specific, fixed-seed discovery without unrestricted search. |
| <code>source_registry.py</code> | Declare adapter IDs, official hosts, seed paths, document types, and source limitations. |
| <code>evidence_validator.py</code> | Verify provenance, entity/subject match, supported fields, and evidence completeness. |
| <code>result_merger.py</code> | Deduplicate evidence and derive the aggregate status without turning non-discovery into nonexistence. |
| <code>audit.py</code> | Emit bounded operational/audit events without logging secrets or complete retrieved documents. |
| <code>orchestrator.py</code> | Coordinate trigger, cache, adapters, extraction, validation, merge, and retry. |
| <code>__init__.py</code> | Expose the package entry points used by Flask. |

## 2. Strict trigger contract

### Inputs

The detector may use only the request fields supplied to the Section 4 endpoint or the corresponding structured values already produced by the PIO pipeline:

- <code>query</code>
- <code>rti_extraction</code>
- <code>legal_analysis</code>
- operator configuration

The user cannot supply a host, seed URL, redirect target, adapter implementation, or arbitrary search scope.

### Positive trigger

Verification is triggered only when a supported signal identifies one of these bounded intents:

1. An explicit Section 4(1)(b) proactive-disclosure question, including a recognized sub-clause.
2. A structured legal-analysis signal that the requested item is a Section 4(1)(b) disclosure candidate.
3. A narrow tender-publication intent for official tender notice, corrigendum, award/result, work-order, contract-listing, or related publication evidence.
4. A structured semantic trigger only for ambiguous cases when <code>SECTION4_SEMANTIC_CLASSIFIER_ENABLED=true</code> (the default). It must still produce a recorded reason and must not expand the configured source set. <code>SECTION4_SEMANTIC_TRIGGER_ENABLED</code> remains a compatibility alias.

A mention of Section 4(1)(a), a generic RTI question, a normal legal-research question, or the mere presence of words such as “website” or “online” is insufficient.

Tender intent widens document-type matching only within approved procurement adapters. It never authorizes the system to infer payment, completion, utilization, delivery, acceptance, or financial settlement from a tender publication.

### Trigger object

Every result records the trigger decision:

~~~json
{
  "triggered": true,
  "trigger_reason": "Explicit Section 4(1)(b)(xv) disclosure request",
  "sub_clause": "xv",
  "trigger": {
    "trigger_type": "section_4_1_b",
    "source": "query",
    "confidence": 1.0,
    "reason": "Explicit Section 4(1)(b)(xv) disclosure request",
    "tender_intent": true
  }
}
~~~

<code>confidence</code> describes trigger matching, not truth, legal certainty, document authenticity, or payment status.

### Negative trigger

When the feature is disabled or no supported trigger exists:

- <code>triggered</code> is <code>false</code>.
- <code>status</code> is <code>SEARCH_NOT_TRIGGERED</code>.
- No outbound source request is made.
- <code>searched_sources</code> and <code>found_items</code> are empty.
- The browser does not render a verification card.

## 3. Status contract

The machine status is always one of:

| Status | Required meaning |
| --- | --- |
| <code>FOUND</code> | At least one verified official item supports the requested public-domain field set, with no material requested field or planned-source gap. |
| <code>PARTIALLY_FOUND</code> | At least one verified official item exists, but one or more requested fields remain unsupported, or a material planned source could not be checked. |
| <code>NOT_FOUND</code> | The planned, reachable official sources were checked and no matching verified item was discovered. This means “not found in this bounded check,” never “does not exist.” |
| <code>SOURCE_UNAVAILABLE</code> | A trigger existed, but source failures prevented a reliable bounded check and there is no sufficient verified evidence for <code>FOUND</code>/<code>PARTIALLY_FOUND</code>. |
| <code>SEARCH_NOT_TRIGGERED</code> | The trigger contract rejected the search or the feature was disabled; no source check occurred. |

Aggregation rules:

1. Only evidence with <code>verified=true</code> may contribute to <code>FOUND</code>, <code>PARTIALLY_FOUND</code>, or <code>available_fields</code>.
2. A candidate URL, a search-result title, a snippet, or an unfetched page is not verified evidence.
3. A source timeout, CAPTCHA, JavaScript-only listing, blocked redirect, parser failure, or open circuit is a source limitation/error—not a negative fact.
4. <code>NOT_FOUND</code> is permitted only after at least one relevant planned source completed successfully and no unresolved source failure could reasonably change the bounded result.
5. If verified evidence exists but a requested field such as payment status is not supported, the field stays in <code>missing_fields</code> and the aggregate cannot be promoted to <code>FOUND</code> for that full request.
6. Duplicate documents are merged by canonical official URL/document identity; duplicate appearances do not increase certainty.
7. <code>relevance_score</code> is for ordering within the bounded evidence set. It is not a probability and cannot override provenance requirements.

## 4. Result and evidence contract

The canonical result uses snake_case:

~~~json
{
  "verification_id": "wv_01J...",
  "triggered": true,
  "trigger_reason": "Explicit Section 4(1)(b)(xv) disclosure request",
  "sub_clause": "xv",
  "status": "PARTIALLY_FOUND",
  "organisation": "Public Works Department, Chhattisgarh",
  "subject": "Tender NIT 123/2026",
  "trigger": {
    "trigger_type": "section_4_1_b",
    "source": "legal_analysis",
    "confidence": 1.0,
    "reason": "Section 4(1)(b)(xv) and tender publication were identified",
    "tender_intent": true
  },
  "searched_sources": [
    {
      "source_id": "cg_eproc_current",
      "domain": "cgeproc.cgstate.gov.in",
      "status": "FOUND",
      "results_examined": 3
    }
  ],
  "found_items": [
    {
      "evidence_id": "ev_01J...",
      "title": "Tender Notice NIT 123/2026",
      "url": "https://cgeproc.cgstate.gov.in/nicgep/app?...",
      "domain": "cgeproc.cgstate.gov.in",
      "document_type": "tender_notice",
      "publication_date": "2026-06-10",
      "page_number": null,
      "section_heading": "Latest Active Tenders",
      "matched_text": "Tender reference, department and subject excerpt...",
      "matched_entities": [
        "Public Works Department",
        "NIT 123/2026"
      ],
      "supported_fields": [
        "tender_notice"
      ],
      "relevance_score": 0.93,
      "verified": true
    }
  ],
  "available_fields": [
    "tender_notice"
  ],
  "missing_fields": [
    "payment_status"
  ],
  "verification_timestamp": "2026-07-14T10:30:00+05:30",
  "warnings": [
    "A tender publication is not proof that payment was made.",
    "Non-discovery in this bounded search is not proof of nonexistence."
  ],
  "errors": [],
  "cached": false
}
~~~

### Required top-level fields

| Field | Contract |
| --- | --- |
| <code>verification_id</code> | Opaque server-generated identifier used for source inspection and retry. Never use it as a file path. |
| <code>triggered</code> | Boolean decision from the strict detector. |
| <code>trigger_reason</code> | Human-auditable reason; must not contain a secret or raw fetched document. |
| <code>sub_clause</code> | Normalized Section 4(1)(b) sub-clause when identified; otherwise null. |
| <code>status</code> | One of the five status constants above. |
| <code>organisation</code> | Normalized target public authority/organisation, if available. |
| <code>subject</code> | Bounded subject/reference used for matching. |
| <code>searched_sources</code> | Per-adapter outcome, including unavailable sources and bounded result count. |
| <code>found_items</code> | Canonical list of verified evidence objects. |
| <code>available_fields</code> | Requested fields supported by one or more verified items. |
| <code>missing_fields</code> | Requested fields not supported by the returned verified items. |
| <code>verification_timestamp</code> | ISO 8601 completion time, rendered in IST by the browser. |
| <code>warnings</code> | Non-fatal limitations and mandatory interpretation cautions. |
| <code>errors</code> | Bounded source/system errors safe to return to the caller. |
| <code>cached</code> | Whether this result was returned from a valid cache entry. |

### Per-source fields

Each <code>searched_sources</code> member contains:

- <code>source_id</code>: stable registry ID, not a user-provided name.
- <code>domain</code>: approved official host actually checked.
- <code>status</code>: bounded adapter outcome.
- <code>results_examined</code>: number examined after limits were applied.
- optional <code>error</code>: a sanitized timeout/access/parser/circuit reason.

An unavailable source stays in this array. It must not be silently converted to a zero-result source.

### Evidence fields

Each <code>found_items</code> member contains:

- identity: <code>evidence_id</code>
- provenance: <code>title</code>, <code>url</code>, <code>domain</code>, <code>document_type</code>
- document location: <code>publication_date</code>, <code>page_number</code>, <code>section_heading</code>
- grounded match: <code>matched_text</code>, <code>matched_entities</code>, <code>supported_fields</code>
- ranking: <code>relevance_score</code>
- provenance gate: <code>verified</code>

Optional location metadata may be null when the official source does not publish it. Do not invent a date, page, heading, or entity. <code>matched_text</code> is a short extract from the retrieved official content, not LLM-written prose.

## 5. Official source registry and adapter constraints

These are bounded seeds, not permission to crawl an entire domain. Source access must still pass the configured allow-list, URL security checks, response-size limits, source-specific limits, and the site’s current access rules.

### Supreme Court of India

Canonical host: <code>www.sci.gov.in</code>

Useful fixed seeds:

- <code>https://www.sci.gov.in/sitemap/</code>
- <code>https://www.sci.gov.in/rti/</code>
- <code>https://www.sci.gov.in/notice-category/tenders/</code>
- <code>https://www.sci.gov.in/judgements-case-no/</code>
- <code>https://www.sci.gov.in/daily-order-case-no/</code>

Constraints:

- The human <code>/sitemap/</code> is usable; the XML sitemap routes observed during the source audit led to a missing WordPress sitemap.
- Judgment and daily-order searches require JavaScript and CAPTCHA.
- The adapter may retain those pages as official gateways, but it must not automate or bypass their CAPTCHA.
- Public static pages/direct documents may be processed when otherwise permitted.

### Central Information Commission

Canonical host: <code>cic.gov.in</code>

Useful fixed seeds:

- <code>https://cic.gov.in/sitemap</code>
- <code>https://cic.gov.in/rti-disclosoures</code> — the misspelling is the official route
- <code>https://cic.gov.in/tender-notification</code>
- <code>https://cic.gov.in/archive-tender-notification</code>
- <code>https://cic.gov.in/decision</code>

The decisions gateway links to:

- <code>https://dsscic.nic.in/cause-list-report-web/view-decision/1</code>
- <code>https://dsscic.nic.in/cause-list-report-web/view-decision-old-all/1</code>
- <code>https://dsscic.nic.in/cause-list-report-web/registry-cause-list/1</code>

Constraints:

- The static Section 4(1)(b) I–XVII disclosure page and linked PDFs are preferred.
- Decision/cause-list searches require image CAPTCHA and must not be automated.
- CIC robots rules disallow internal <code>/search/</code> routes.
- <code>dsscic.nic.in</code> is not in the default host list. A gateway link is metadata only unless an operator explicitly approves that exact official host; approval still does not authorize CAPTCHA bypass.
- <code>/sitemap</code> is the HTML sitemap; <code>/sitemap.xml</code> was not a usable sitemap during the audit.

### Chhattisgarh State Information Commission

Canonical host: <code>siccg.gov.in</code>

Primary Section 4 seed:

- <code>https://siccg.gov.in/sec_4_1_XV_13.html</code>

That static page exposes links across the Section 4 I–XVII chain.

Constraints:

- Prefer the static disclosure pages to the homepage case-search form.
- The host was intermittently slow during the audit; bounded timeout, retry/backoff, and honest <code>SOURCE_UNAVAILABLE</code> reporting are required.
- No dependable sitemap was verified.
- Do not claim that a case search can be automated unless its current form contract is separately validated.

### Chhattisgarh RTI Online

Canonical host: <code>rtionline.cg.gov.in</code>; the <code>www</code> alias also resolves.

Known public paths:

- <code>https://rtionline.cg.gov.in/</code>
- <code>https://www.rtionline.cg.gov.in/pioRegstration</code> — official spelling/casing

Constraints:

- This is a React single-page application. Plain HTTP retrieval returns an application shell that says JavaScript is required.
- Its <code>/sitemap.xml</code> response observed during the audit was the SPA HTML fallback, not an XML sitemap.
- No dependable server-rendered public listing or documented public search API was identified.
- With Playwright disabled, the adapter should report the limitation rather than guess private SPA endpoints.
- If browser rendering is enabled later, it remains subject to the same allow-list and cannot bypass login/CAPTCHA.

### Government e-Marketplace

Canonical hosts: <code>gem.gov.in</code> and <code>bidplus.gem.gov.in</code>

Useful fixed seeds:

- <code>https://gem.gov.in/sitemap</code>
- <code>https://gem.gov.in/sitemap.xml</code>
- <code>https://bidplus.gem.gov.in/all-bids</code>
- <code>https://gem.gov.in/view_contracts</code>

Constraints:

- The XML sitemap is available and may be consumed subject to bounds.
- The all-bids listing is JavaScript/XHR-driven. Do not assume a stable HTML pagination contract and do not reverse-engineer private endpoints.
- Store the final canonical URL because older bid links can redirect through GeM URL-tracking routes.
- Do not enter the GeM SSO/login flow.
- A GeM bid/contract listing supports publication evidence only; it does not prove payment.

### Central Public Procurement Portal

Canonical application:

- <code>https://eprocure.gov.in/eprocure/app</code>

Useful fixed front-end views append <code>?page=...&amp;service=page</code>:

- <code>FrontEndAdvancedSearch</code>
- <code>FrontEndLatestActiveTenders</code>
- <code>FrontEndListTendersbyDate</code>
- <code>FrontEndLatestActiveCorrigendums</code>
- <code>FrontEndTendersByLocation</code>
- <code>FrontEndTendersByOrganisation</code>
- <code>FrontEndTendersByClassification</code>
- <code>FrontEndTendersInArchive</code>
- <code>WebTenderStatusLists</code>
- <code>WebCancelledTenderLists</code>
- <code>SiteMap</code>

The ePublishing entry point is:

- <code>https://eprocure.gov.in/epublish/app?service=home</code>

Constraints:

- Latest listings/navigation are server-rendered enough for bounded discovery.
- Search/detail flows can be stateful Tapestry/JavaScript/session workflows. Adapters must not synthesize hidden form state or use authenticated bid-submission paths.
- Missing <code>robots.txt</code> or <code>sitemap.xml</code> is not permission for unrestricted crawling.

### Chhattisgarh e-procurement: current and legacy are distinct

The current canonical NIC GePNIC portal is:

- <code>https://cgeproc.cgstate.gov.in/nicgep/app</code>

The root <code>https://cgeproc.cgstate.gov.in/</code> uses a client-side refresh to that application. Useful fixed views append <code>?page=...&amp;service=page</code>:

- <code>FrontEndAdvancedSearch</code>
- <code>FrontEndLatestActiveTenders</code>
- <code>FrontEndListTendersbyDate</code>
- <code>FrontEndLatestActiveCorrigendums</code>
- <code>ResultOfTenders</code>
- <code>FrontEndTendersByLocation</code>
- <code>FrontEndTendersByOrganisation</code>
- <code>FrontEndTendersByClassification</code>
- <code>FrontEndTendersInArchive</code>
- <code>WebTenderStatusLists</code>
- <code>WebCancelledTenderLists</code>
- <code>WebAwards</code>
- <code>SiteMap</code>

The official reporting gateway is <code>https://gepnicreports.gov.in/eprocreports/cg/</code>, but that host is not in the default allow-list and must not be followed unless explicitly operator-approved.

The legacy CHiPS portal is separate:

- <code>https://eproc.cgstate.gov.in/</code>
- <code>https://eproc.cgstate.gov.in/CHEPS/security/getSignInAction.do</code>

The legacy root uses an HTML meta refresh to the CHEPS application. It is not an HTTP alias or redirect to <code>cgeproc.cgstate.gov.in</code>, and official Chhattisgarh department documents still cite it. Therefore:

- <code>cgeproc.cgstate.gov.in</code> is the canonical source for the current adapter.
- <code>eproc.cgstate.gov.in</code> remains a separate legacy/historical adapter.
- Do not deduplicate one host into the other.
- Revalidate a meta-refresh target through the normal URL security policy before following it.
- Do not automate bidder login or submission on either portal.

## 6. Configuration

Copy settings from <code>FG/05_webui/.env.example</code> into the deployment’s <code>FG/05_webui/.env</code>. Source selection remains server-side.

### Feature and trigger controls

| Variable | Default | Meaning |
| --- | ---: | --- |
| <code>SECTION4_WEB_VERIFICATION_ENABLED</code> | <code>true</code> | Master switch. When false, return <code>SEARCH_NOT_TRIGGERED</code> and make no source request. |
| <code>SECTION4_LIVE_VERIFICATION_ENABLED</code> | <code>true</code> | Allow live retrieval from approved adapters. |
| <code>SECTION4_LOCAL_INDEX_ENABLED</code> | <code>true</code> | Allow the service’s local cache/index path. |
| <code>SECTION4_SEMANTIC_CLASSIFIER_ENABLED</code> | <code>true</code> | Permit the existing structured LLM only for ambiguous routing. It cannot choose or fetch a URL. <code>SECTION4_SEMANTIC_TRIGGER_ENABLED</code> is accepted as a compatibility alias. |
| <code>SECTION4_PLAYWRIGHT_ENABLED</code> | <code>false</code> | Reserved deployment flag. This package does not ship a Playwright runtime; JavaScript-only pages remain explicitly unavailable unless a separately reviewed renderer is added. CAPTCHA/login bypass is never permitted. |
| <code>SECTION4_OCR_ENABLED</code> | <code>true</code> | Permit bounded OCR/extraction for safely retrieved public documents when needed. |
| <code>SECTION4_DEBUG</code> | <code>false</code> | Additional diagnostics. Never log secrets or full retrieved documents. |

### Source boundaries

| Variable | Default/role |
| --- | --- |
| <code>SECTION4_ALLOWED_DOMAINS</code> | Exact built-in official-host allow-list from <code>.env.example</code>. |
| <code>SECTION4_DEPARTMENT_DOMAINS</code> | Optional operator-controlled exact official department hosts. Never populate from a user query. |
| <code>SECTION4_USER_AGENT</code> | <code>CHiPS-RTI-Verification/1.0</code> |
| <code>SECTION4_CHATBOT_TEAM</code> | <code>rti-assistant</code>; bounded audit label, never user-controlled |
| <code>SECTION4_MAX_RESULTS_PER_SOURCE</code> | <code>10</code> candidates examined per adapter. |
| <code>SECTION4_MAX_VERIFIED_RESULTS</code> | <code>5</code> verified evidence items returned. |

### Network and content limits

| Variable | Default |
| --- | ---: |
| <code>SECTION4_REQUEST_TIMEOUT_SECONDS</code> | <code>30</code> |
| <code>SECTION4_CONNECT_TIMEOUT_SECONDS</code> | <code>8</code> |
| <code>SECTION4_TOTAL_TIMEOUT_SECONDS</code> | <code>45</code>; hard synchronous verification deadline for the PIO response |
| <code>SECTION4_MAX_REDIRECTS</code> | <code>3</code> |
| <code>SECTION4_MAX_HTML_BYTES</code> | <code>10485760</code> |
| <code>SECTION4_MAX_PDF_BYTES</code> | <code>104857600</code> |
| <code>SECTION4_MIN_REQUEST_INTERVAL_SECONDS</code> | <code>1.0</code> per host |
| <code>SECTION4_MAX_CONCURRENT_PER_DOMAIN</code> | <code>2</code>; optional hard cap per exact host |
| <code>SECTION4_MAX_REQUESTS_PER_DOMAIN_PER_DAY</code> | <code>2000</code>; enforced in-memory daily budget with counters exposed by the limiter snapshot |
| <code>SECTION4_REQUESTS_PER_SECOND_PER_DOMAIN</code> | Optional compatibility override; the minimum-interval setting is preferred |
| <code>SECTION4_CIRCUIT_FAILURE_THRESHOLD</code> | <code>3</code> consecutive failures |
| <code>SECTION4_CIRCUIT_RESET_SECONDS</code> | <code>300</code> |

Additional extractor safety bounds currently supported by the package are <code>SECTION4_MAX_EXTRACTED_CHARS</code> (default 500000), <code>SECTION4_MAX_PDF_PAGES</code> (default 500), and <code>SECTION4_MAX_OCR_PAGES</code> (default 20). Keep them finite. <code>SECTION4_SEMANTIC_TRIGGER_ENABLED</code> and <code>SECTION4_CIRCUIT_COOLDOWN_SECONDS</code> are compatibility aliases for the preferred classifier and circuit-reset settings.

### Cache controls

| Variable | Default |
| --- | ---: |
| <code>SECTION4_CACHE_TTL_SECONDS</code> | <code>21600</code> |
| <code>SECTION4_DISCLOSURE_TTL_SECONDS</code> | <code>86400</code> |
| <code>SECTION4_STATIC_TTL_SECONDS</code> | <code>604800</code> |
| <code>SECTION4_TENDER_TTL_SECONDS</code> | <code>10800</code> |
| <code>SECTION4_CACHE_PATH</code> | <code>cache/section4_verification.sqlite3</code> |
| <code>SECTION4_FORCE_REFRESH_TOKEN</code> | Empty; all force-refresh requests must be rejected until an operator configures server-side authorization. |

Category TTLs allow relatively volatile tender results to expire sooner than static disclosure pages. The generic TTL is the fallback.

The default allowed-host list is:

~~~text
sci.gov.in,www.sci.gov.in,api.sci.gov.in,
cic.gov.in,www.cic.gov.in,
siccg.gov.in,www.siccg.gov.in,
rtionline.cg.gov.in,
cgeproc.cgstate.gov.in,eproc.cgstate.gov.in,
gem.gov.in,www.gem.gov.in,bidplus.gem.gov.in,
eprocure.gov.in,www.eprocure.gov.in
~~~

Do not add a wildcard such as <code>*.gov.in</code>. Review and add each required exact official host explicitly.

## 7. Dependencies, installation, run, and test commands

Required packages are declared in the repository-level <code>requirements.txt</code>. The verifier specifically relies on the existing Flask/requests/PDF stack and adds Beautiful Soup for bounded HTML parsing:

- Flask
- requests
- beautifulsoup4
- PyMuPDF and/or the repository’s existing PDF extraction stack
- python-dotenv
- pytest for tests
- Python’s built-in sqlite3

Playwright is not a default dependency. Leave <code>SECTION4_PLAYWRIGHT_ENABLED=false</code> unless the operator deliberately installs and reviews a browser-rendering deployment.

### Install

From the repository root in PowerShell:

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if (-not (Test-Path 'FG\05_webui\.env')) {
    Copy-Item 'FG\05_webui\.env.example' 'FG\05_webui\.env'
}

Set-Location 'FG\05_webui\nodejs'
npm install
Set-Location '..\..\..'
~~~

Review <code>FG/05_webui/.env</code> before starting. Do not commit its secrets.

### Run Flask directly

~~~powershell
python FG\05_webui\app.py
~~~

The default Flask URL is <code>http://localhost:5000</code>. This backend is intended to remain behind the existing Express/selection-server deployment boundary.

### Run the Express UI/proxy

In a second PowerShell:

~~~powershell
Set-Location FG\05_webui\nodejs
npm start
~~~

The default UI URL is <code>http://localhost:3002</code>, with <code>/api/*</code> proxied to Flask.

### Test commands

Run the targeted Section 4 suite:

~~~powershell
$section4Tests = Get-ChildItem -LiteralPath tests -Filter 'test_section4_*.py' |
    Select-Object -ExpandProperty FullName
python -m pytest -q $section4Tests
~~~

Run the frontend source-contract checks directly:

~~~powershell
python -m pytest -q tests/test_section4_frontend.py
node --check FG\05_webui\nodejs\public\app.js
~~~

Run the broader repository test suite when integration dependencies are available:

~~~powershell
python -m pytest -q
~~~

The final integrated results from these commands are recorded in the verification-results section at the end.

## 8. Flask API

All JSON field names use snake_case. Browser calls normally go through the existing Express <code>/api</code> proxy. Examples below show direct Flask URLs.

### 8.1 Start or retrieve a Section 4 verification

<code>POST /api/web-verification/section-4</code>

Request:

~~~json
{
  "query": "क्या लोक निर्माण विभाग की निविदा NIT 123/2026 की सूचना और भुगतान विवरण सार्वजनिक वेबसाइट पर उपलब्ध हैं?",
  "rti_extraction": {
    "organisation": "Public Works Department, Chhattisgarh",
    "subject": "NIT 123/2026",
    "requested_fields": [
      "tender_notice",
      "payment_status"
    ]
  },
  "legal_analysis": {
    "section_4_1_b": true,
    "sub_clause": "xv",
    "tender_intent": true
  },
  "force_refresh": false
}
~~~

Contract:

- <code>query</code> must be a bounded string.
- <code>rti_extraction</code> and <code>legal_analysis</code> are optional structured objects, not raw instructions to the fetcher.
- Unknown nested fields do not become domains, URLs, commands, or adapter names.
- <code>force_refresh=true</code> requires separate server-side authorization using the configured force-refresh secret. A client cannot authorize itself by placing the secret or a URL in the JSON body.

Successful response:

~~~json
{
  "success": true,
  "web_verification": {
    "verification_id": "wv_01J...",
    "triggered": true,
    "trigger_reason": "Explicit Section 4(1)(b)(xv) disclosure request",
    "sub_clause": "xv",
    "status": "PARTIALLY_FOUND",
    "organisation": "Public Works Department, Chhattisgarh",
    "subject": "NIT 123/2026",
    "trigger": {
      "trigger_type": "section_4_1_b",
      "source": "query",
      "confidence": 1.0,
      "reason": "Explicit Section 4(1)(b)(xv) disclosure request",
      "tender_intent": true
    },
    "searched_sources": [
      {
        "source_id": "cg_eproc_current",
        "domain": "cgeproc.cgstate.gov.in",
        "status": "FOUND",
        "results_examined": 3
      }
    ],
    "found_items": [
      {
        "evidence_id": "ev_01J...",
        "title": "Tender Notice NIT 123/2026",
        "url": "https://cgeproc.cgstate.gov.in/nicgep/app?...",
        "domain": "cgeproc.cgstate.gov.in",
        "document_type": "tender_notice",
        "publication_date": "2026-06-10",
        "page_number": null,
        "section_heading": "Latest Active Tenders",
        "matched_text": "Tender reference, department and subject excerpt...",
        "matched_entities": [
          "Public Works Department",
          "NIT 123/2026"
        ],
        "supported_fields": [
          "tender_notice"
        ],
        "relevance_score": 0.93,
        "verified": true
      }
    ],
    "available_fields": [
      "tender_notice"
    ],
    "missing_fields": [
      "payment_status"
    ],
    "verification_timestamp": "2026-07-14T10:30:00+05:30",
    "warnings": [
      "A tender publication is not proof that payment was made."
    ],
    "errors": [],
    "cached": false
  }
}
~~~

Every production <code>available_fields</code> value must be backed by a corresponding verified <code>found_items</code> member.

Non-triggered response is still a successful classification:

~~~json
{
  "success": true,
  "web_verification": {
    "verification_id": "wv_01J...",
    "triggered": false,
    "trigger_reason": "No supported Section 4(1)(b) or tender-publication intent",
    "sub_clause": null,
    "status": "SEARCH_NOT_TRIGGERED",
    "organisation": null,
    "subject": null,
    "trigger": {
      "trigger_type": "none",
      "source": "query",
      "confidence": 1.0,
      "reason": "No supported trigger",
      "tender_intent": false
    },
    "searched_sources": [],
    "found_items": [],
    "available_fields": [],
    "missing_fields": [],
    "verification_timestamp": "2026-07-14T10:30:00+05:30",
    "warnings": [],
    "errors": [],
    "cached": false
  }
}
~~~

Invalid request example:

~~~json
{
  "success": false,
  "error": {
    "code": "INVALID_REQUEST",
    "message": "query must be a non-empty string"
  }
}
~~~

Expected HTTP class: <code>400</code>. A disabled feature should return the normal <code>SEARCH_NOT_TRIGGERED</code> result rather than falsely reporting a source failure.

Unauthorized force-refresh example:

~~~json
{
  "success": false,
  "error": {
    "code": "FORCE_REFRESH_FORBIDDEN",
    "message": "Force refresh is not authorized"
  }
}
~~~

Expected HTTP class: <code>403</code>. Ordinary cached verification remains available.

### 8.2 Read bounded verified sources

<code>GET /api/web-verification/sources/&lt;verification_id&gt;</code>

This endpoint returns the stored, bounded verified evidence for one opaque verification ID. It must not refetch arbitrary URLs and must never interpret the ID as a filesystem path.

Successful response:

~~~json
{
  "success": true,
  "verification_id": "wv_01J...",
  "sources": [
    {
      "evidence_id": "ev_01J...",
      "title": "Tender Notice NIT 123/2026",
      "url": "https://cgeproc.cgstate.gov.in/nicgep/app?...",
      "domain": "cgeproc.cgstate.gov.in",
      "document_type": "tender_notice",
      "publication_date": "2026-06-10",
      "page_number": null,
      "section_heading": "Latest Active Tenders",
      "matched_text": "Tender reference, department and subject excerpt...",
      "matched_entities": [
        "Public Works Department",
        "NIT 123/2026"
      ],
      "supported_fields": [
        "tender_notice"
      ],
      "relevance_score": 0.93,
      "verified": true
    }
  ],
  "count": 1
}
~~~

The number returned is bounded by <code>SECTION4_MAX_VERIFIED_RESULTS</code>. Unverified candidates are not exposed as verified sources.

Unknown/expired ID:

~~~json
{
  "success": false,
  "error": {
    "code": "VERIFICATION_NOT_FOUND",
    "message": "Verification was not found or has expired"
  }
}
~~~

Expected HTTP class: <code>404</code>.

### 8.3 Retry unavailable sources

<code>POST /api/web-verification/&lt;verification_id&gt;/retry</code>

The UI calls this only when the existing aggregate status is <code>SOURCE_UNAVAILABLE</code>.

Request:

~~~json
{
  "answer_language": "hi"
}
~~~

Behavior:

- Reuse the stored trusted query plan.
- Retry only unavailable/eligible sources; do not accept a new host or URL.
- Preserve existing verified evidence while merging a successful retry.
- Do not regenerate the PIO advisory.
- Apply the normal per-host interval, circuit breaker, timeout, redirect, and size controls.

Successful response:

~~~json
{
  "success": true,
  "web_verification": {
    "verification_id": "wv_01J...",
    "triggered": true,
    "trigger_reason": "Explicit Section 4(1)(b)(xv) disclosure request",
    "sub_clause": "xv",
    "status": "PARTIALLY_FOUND",
    "organisation": "Public Works Department, Chhattisgarh",
    "subject": "NIT 123/2026",
    "trigger": {
      "trigger_type": "section_4_1_b",
      "source": "query",
      "confidence": 1.0,
      "reason": "Explicit Section 4(1)(b)(xv) disclosure request",
      "tender_intent": true
    },
    "searched_sources": [
      {
        "source_id": "cg_eproc_current",
        "domain": "cgeproc.cgstate.gov.in",
        "status": "FOUND",
        "results_examined": 3
      }
    ],
    "found_items": [
      {
        "evidence_id": "ev_01J...",
        "title": "Tender Notice NIT 123/2026",
        "url": "https://cgeproc.cgstate.gov.in/nicgep/app?...",
        "domain": "cgeproc.cgstate.gov.in",
        "document_type": "tender_notice",
        "publication_date": "2026-06-10",
        "page_number": null,
        "section_heading": "Latest Active Tenders",
        "matched_text": "Tender reference, department and subject excerpt...",
        "matched_entities": [
          "Public Works Department",
          "NIT 123/2026"
        ],
        "supported_fields": [
          "tender_notice"
        ],
        "relevance_score": 0.93,
        "verified": true
      }
    ],
    "available_fields": [
      "tender_notice"
    ],
    "missing_fields": [
      "payment_status"
    ],
    "verification_timestamp": "2026-07-14T10:35:00+05:30",
    "warnings": [
      "A tender publication is not proof that payment was made."
    ],
    "errors": [],
    "cached": false
  }
}
~~~

Unknown ID uses <code>404</code> with <code>VERIFICATION_NOT_FOUND</code>. A syntactically invalid ID uses <code>400</code>. If no source is eligible for retry, return a bounded conflict/error rather than launching a new unrestricted search.

No eligible source example:

~~~json
{
  "success": false,
  "error": {
    "code": "RETRY_NOT_AVAILABLE",
    "message": "This verification has no unavailable source eligible for retry"
  }
}
~~~

Expected HTTP class: <code>409</code>. On failure, the browser keeps the previous evidence/advisory and shows a localized error toast.

### 8.4 Inspect verifier health

<code>GET /api/web-verification/health</code>

The health response is an operational snapshot. It must not leak secrets, cache contents, full URLs containing sensitive query parameters, or retrieved text.

Example:

~~~json
{
  "success": true,
  "enabled": true,
  "live_verification_enabled": true,
  "cache": {
    "enabled": true,
    "status": "ready"
  },
  "adapters": [
    {
      "source_id": "cic_disclosures",
      "domain": "cic.gov.in",
      "status": "ready",
      "circuit_state": "closed"
    },
    {
      "source_id": "siccg_disclosures",
      "domain": "siccg.gov.in",
      "status": "degraded",
      "circuit_state": "open",
      "error": "Recent source timeouts"
    }
  ]
}
~~~

Health should report configured adapter/circuit/cache state quickly. It should not synchronously crawl every official website merely because a monitoring system called the endpoint.

Initialization failure example:

~~~json
{
  "success": false,
  "enabled": true,
  "status": "unavailable",
  "error": {
    "code": "VERIFIER_HEALTH_UNAVAILABLE",
    "message": "Section 4 verifier health could not be read"
  }
}
~~~

Expected HTTP class: <code>503</code>. The response must remain sanitized; detailed local exceptions belong only in protected server logs.

## 9. PIO integration and Hindi UI example

For the primary PIO responses, Flask attaches:

~~~json
{
  "answer": "...existing PIO advisory...",
  "advisory_id": "...",
  "web_verification": {
    "verification_id": "wv_01J...",
    "status": "SOURCE_UNAVAILABLE",
    "triggered": true
  }
}
~~~

The same top-level contract applies to the final event of <code>/api/query/stream</code> and to <code>/api/pio/upload-pdf</code>. The browser stores it as part of the assistant message and renders the evidence card before the existing PIO analysis details.

Example Hindi presentation:

~~~text
सार्वजनिक-डोमेन सत्यापन
स्थिति: आंशिक रूप से मिला
सत्यापित आधिकारिक दस्तावेज़: 1
खोजे गए आधिकारिक डोमेन: cgeproc.cgstate.gov.in
अंतिम जाँच: 14 जुल॰ 2026, 10:30 am IST

उपलब्ध
• निविदा सूचना

अनुपलब्ध
• भुगतान स्थिति

मिलान किया गया साक्ष्य
“...official source excerpt...”

आधिकारिक स्रोत खोलें: cgeproc.cgstate.gov.in
~~~

For <code>SOURCE_UNAVAILABLE</code>, the card displays:

- <code>स्थिति: स्रोत अनुपलब्ध</code>
- <code>कुछ आधिकारिक स्रोतों की जाँच नहीं हो सकी।</code>
- retry button <code>अनुपलब्ध स्रोतों को पुनः जाँचें</code>

Only <code>FOUND</code>, <code>PARTIALLY_FOUND</code>, <code>NOT_FOUND</code>, and <code>SOURCE_UNAVAILABLE</code> produce visible cards. <code>SEARCH_NOT_TRIGGERED</code> remains invisible.

Frontend evidence controls:

- Only <code>found_items</code> with <code>verified=true</code> are canonical evidence.
- A visible evidence link must be credential-free HTTPS on a <code>.gov.in</code> or <code>.nic.in</code> hostname.
- Link labels show the official hostname, open in a new tab, and use <code>rel="noopener noreferrer"</code>.
- Source title, metadata, and matched evidence are inserted as text, not trusted HTML.
- The matched evidence display is bounded to 480 characters.
- Retry is available only for <code>SOURCE_UNAVAILABLE</code>.
- A retry failure preserves the previous result and advisory.

Machine fields/statuses stay in English snake_case. Labels are localized; source excerpts remain in their original language.

## 10. Security boundaries

### SSRF and URL policy

Backend validation is authoritative; frontend checks are defense in depth.

Every outbound request and every redirect/meta-refresh hop must:

1. Use an allowed web scheme. Production evidence links are HTTPS.
2. Have no embedded username/password.
3. Use an expected port.
4. Match an exact operator-approved official hostname.
5. Resolve only to permitted public addresses.
6. Reject loopback, private, link-local, multicast, reserved, unspecified, and cloud-metadata destinations for IPv4 and IPv6.
7. Re-resolve and revalidate every redirect target to reduce DNS-rebinding risk.
8. Stay within <code>SECTION4_MAX_REDIRECTS</code>.
9. Enforce connect/read timeout and streamed byte limits before parsing.
10. Accept only expected content types and validate file signatures where appropriate.

Reject <code>file:</code>, <code>data:</code>, <code>ftp:</code>, <code>gopher:</code>, UNC paths, local drive paths, user-info URLs, non-approved ports, and numeric/encoded attempts to reach local addresses.

The source registry—not the query—chooses URLs. <code>SECTION4_DEPARTMENT_DOMAINS</code> is deployment configuration and must never be modified through an API request.

### Redirect, JavaScript, CAPTCHA, and login policy

- Revalidate normal redirects and HTML meta refreshes before following.
- Do not execute arbitrary scripts returned by a source.
- Optional browser rendering is for public JavaScript presentation only.
- Never solve/bypass CAPTCHA or automate authentication.
- Never submit a tender/bid, alter a government system, or call a private/internal API.
- A JavaScript-only/CAPTCHA-only source may legitimately yield <code>SOURCE_UNAVAILABLE</code>.

### Prompt-injection resistance

All retrieved web content is untrusted data, even on an official host.

- Strip scripts, styles, hidden controls, navigation noise, and active content during extraction.
- Never obey instructions contained in a page/PDF, comment, metadata field, or matched passage.
- Never let fetched content change the allowed domains, source plan, tool selection, limits, system prompt, or status rules.
- Do not expose environment variables, cache records, local files, or model/system prompts to fetched content.
- Derive <code>verified</code> from deterministic provenance/validation gates, not from a document saying that it is “verified.”
- If an LLM is used for optional analysis, provide only bounded extracted text as quoted evidence and require deterministic post-validation of every returned URL/field.

### Output safety and interpretation

- Do not render source HTML directly.
- Never mark a non-official URL as verified evidence.
- Always preserve source failures and interpretation warnings.
- Never say “payment made” based only on a tender, corrigendum, award, contract listing, purchase order, or work order.
- Never say “does not exist” merely because the bounded adapters returned no item.
- Never present relevance score as legal confidence.

### Force refresh

<code>force_refresh</code> increases outbound traffic and can bypass a valid cache entry, so it is privileged:

- Leave <code>SECTION4_FORCE_REFRESH_TOKEN</code> empty to deny all force-refresh requests.
- Authenticate force refresh through server-side request authorization; never accept the configured secret as evidence or a source selector.
- Compare secrets safely.
- Never log the token.
- Normal cached verification and unavailable-source retry remain separate operations.

### Deployment boundary

The Express proxy currently forwards <code>/api</code> to Flask. This package does not itself provide user authentication or a complete inbound abuse-control layer. Production deployment must retain the application’s authentication/reverse-proxy boundary and apply request-size, concurrency, and per-user/IP limits there. The outbound per-host interval is a source-politeness control, not a substitute for inbound API rate limiting.

## 11. Cache, rate limiting, circuit breaker, and audit logging

### SQLite cache

The default cache is <code>cache/section4_verification.sqlite3</code>. It stores normalized verification records/evidence needed for TTL reuse, source inspection, and retry.

- Cache keys must be derived from normalized trusted inputs and the configured source plan, not raw arbitrary URLs.
- <code>cached=true</code> means a non-expired result was reused.
- Tender entries use the shorter tender TTL.
- Static Section 4 disclosure pages may use the static/disclosure TTLs.
- Expired entries are not positive or negative evidence.
- Force refresh does not weaken validation; it only bypasses eligible cache reuse.
- Treat the database as application data: restrict filesystem access and do not serve it through Flask/static routes.
- The cache is intentionally ignored by Git.

### No migration step

No manual database migration is required. The cache module initializes SQLite and its required tables/indexes automatically with idempotent <code>CREATE TABLE IF NOT EXISTS</code>-style setup when the service first opens the configured cache.

Therefore:

- Do not run Alembic or import a SQL dump for this feature.
- Ensure the Flask process can create/write the configured cache directory.
- A missing database means a cold cache, not a deployment failure, provided the directory is writable.
- Stop the application before intentionally archiving/removing the database.

### Per-host pacing and circuit breaking

- Wait at least <code>SECTION4_MIN_REQUEST_INTERVAL_SECONDS</code> between outbound requests to the same host.
- Never use parallelism to evade a host’s minimum interval.
- After <code>SECTION4_CIRCUIT_FAILURE_THRESHOLD</code> consecutive qualifying failures, open that adapter/host circuit.
- While open, return a bounded source-unavailable record instead of repeatedly hammering the host.
- After <code>SECTION4_CIRCUIT_RESET_SECONDS</code>, permit a controlled probe.
- A successful response may close/reset the circuit; a content “not found” result is not a network failure.

### Logging and audit

Useful audit fields include:

- <code>verification_id</code>
- route/operation
- trigger decision/type/source
- source ID and official domain
- cache hit/miss
- adapter status and results examined
- HTTP status class, duration, timeout/circuit category
- aggregate status and verified-item count
- retry/force-refresh decision

Do not log:

- force-refresh tokens or other secrets
- cookies, authorization headers, or session identifiers
- entire request bodies, fetched HTML/PDF text, or full matched documents
- local filesystem paths exposed to clients
- raw exception traces in production API responses

<code>SECTION4_DEBUG=true</code> may increase operator diagnostics, but it must not disable redaction or security checks.

## 12. Rollback

### Immediate operational rollback

1. Set <code>SECTION4_WEB_VERIFICATION_ENABLED=false</code> in <code>FG/05_webui/.env</code>.
2. Restart Flask workers.
3. Confirm the health endpoint reports disabled and eligible requests return <code>SEARCH_NOT_TRIGGERED</code> without outbound traffic.

This preserves the existing PIO advisory, upload, query, and precedent flow. The frontend will not render a card for <code>SEARCH_NOT_TRIGGERED</code>.

### Code rollback

If the implementation must be removed:

1. Disable it first and restart.
2. Revert only the Section 4 Flask integration, package, frontend card/retry, tests, <code>SECTION4_*</code> example settings, cache ignore rule, and the Beautiful Soup dependency if no other component needs it.
3. Preserve unrelated working-tree changes.
4. Keep or archive the SQLite cache for audit needs; delete it only after the process is stopped and retention requirements are checked.
5. Run the existing non-Section-4 PIO/query/upload tests to confirm the original flow remains intact.

## 13. Final verification checklist

### Configuration and startup

- [ ] Dependencies install from <code>requirements.txt</code>.
- [ ] <code>FG/05_webui/.env</code> contains reviewed <code>SECTION4_*</code> values.
- [ ] No wildcard/user-controlled domain is configured.
- [ ] Flask starts with the cache directory writable.
- [ ] SQLite initializes automatically; no migration command is needed.
- [ ] Express proxy can reach all four Flask routes.

### Trigger and status

- [ ] A generic RTI query returns <code>SEARCH_NOT_TRIGGERED</code> and causes zero outbound requests.
- [ ] An explicit Section 4(1)(b) query records trigger type/source/reason/sub-clause.
- [ ] Tender intent selects only approved procurement adapters.
- [ ] <code>FOUND</code> requires verified official evidence.
- [ ] Missing requested fields produce <code>PARTIALLY_FOUND</code> where evidence exists.
- [ ] A completed zero-match check says <code>NOT_FOUND</code> with a nonexistence warning.
- [ ] Material source failures produce <code>SOURCE_UNAVAILABLE</code>, not <code>NOT_FOUND</code>.
- [ ] A tender/work-order/award result does not support <code>payment_status</code> by itself.

### Source and security behavior

- [ ] All default seeds resolve only through exact approved official hosts.
- [ ] Current <code>cgeproc.cgstate.gov.in</code> and legacy <code>eproc.cgstate.gov.in</code> remain separate adapters.
- [ ] Every HTTP redirect and legacy meta refresh is revalidated.
- [ ] Loopback/private/link-local/metadata/encoded SSRF attempts are rejected.
- [ ] Credentials, non-approved ports, unsupported schemes, and oversized responses are rejected.
- [ ] CAPTCHA/login pages are reported as limitations and never bypassed.
- [ ] JS-only portals report an honest limitation when browser rendering is disabled.
- [ ] Fetched instructions cannot alter the source plan or security configuration.
- [ ] No paid or unrestricted search service is called.

### Cache and resilience

- [ ] Identical eligible requests reuse a valid cache entry and set <code>cached=true</code>.
- [ ] Static/disclosure/tender TTL selection is correct.
- [ ] Force refresh is denied when no secret is configured.
- [ ] Force refresh does not bypass allow-list/evidence validation.
- [ ] Per-host request spacing is enforced.
- [ ] Repeated source failures open the circuit and reset after the configured interval.
- [ ] Retry reuses the stored plan and preserves prior evidence.

### API and UI

- [ ] <code>POST /api/web-verification/section-4</code> validates its body and returns the canonical schema.
- [ ] <code>GET /api/web-verification/sources/&lt;verification_id&gt;</code> returns only bounded verified items.
- [ ] <code>POST /api/web-verification/&lt;verification_id&gt;/retry</code> handles unknown/invalid IDs safely.
- [ ] <code>GET /api/web-verification/health</code> returns adapter/cache/circuit state without secrets.
- [ ] Main PIO and PDF-upload results expose top-level <code>web_verification</code>.
- [ ] Stream final payload retains top-level <code>web_verification</code>.
- [ ] The card appears before PIO details for the four visible statuses.
- [ ] <code>SEARCH_NOT_TRIGGERED</code> produces no card.
- [ ] Hindi labels, status, warning, timestamp, field lists, and retry action render correctly.
- [ ] Evidence links are official HTTPS links with safe new-tab attributes.
- [ ] Retry failure keeps the prior advisory/evidence.

### Tests and operational review

- [ ] Run the targeted PowerShell test command above for every <code>tests/test_section4_*.py</code> file.
- [ ] Run <code>python -m pytest -q tests/test_section4_frontend.py</code>.
- [ ] Run <code>node --check FG\05_webui\nodejs\public\app.js</code>.
- [ ] Run the appropriate broader PIO/query/upload regression tests.
- [ ] Inspect logs for useful audit fields and absence of secrets/full document bodies.
- [ ] Record the exact commands, date, environment, pass/fail counts, and known limitations below.

## 14. Verification results

**Status: integrated and validated on 14 July 2026.**

~~~text
Date/time: 2026-07-14, Asia/Kolkata
Base commit/worktree: 55d72943 on branch websearch, with the Section 4 changes uncommitted
Python/Node versions: Python 3.11.15; Node v24.16.0
Configuration profile: defaults from .env.example; secrets not loaded or printed

Commands run:
1. python -B -m pytest -q tests/test_section4_*.py
2. python -B -m pytest -q tests --ignore=tests/test_legal_section_chunker.py --ignore=tests/test_reference_retriever.py
3. node --check FG/05_webui/nodejs/public/app.js
4. python -B -m compileall -q FG/05_webui/services/section4_web_verification FG/05_webui/services/pio_pipeline.py FG/05_webui/app.py
5. A bounded HTTPS retrieval/extraction smoke check against https://www.sci.gov.in/rti/
6. A bounded Supreme Court adapter search/fetch smoke check using an explicit Section 4(1)(b) query

Results:
- Consolidated Section 4 unit/integration/frontend suite: 93 passed in 1.30 s.
- All otherwise collectable repository tests, including Section 4, language, OCR, upload wiring, and PIO tests: 127 passed in 1.39 s.
- JavaScript syntax check: passed.
- Python compile check: passed.
- SCI RTI live retrieval: HTTP 200, approved domain www.sci.gov.in, HTML extracted successfully (248,556 bytes; 10,851 text characters).
- SCI adapter live search/fetch: trigger detected; 3 bounded candidates; the highest-ranked official candidate fetched with HTTP 200 and extracted successfully.

Broader-suite limitation:
- A completely unfiltered `pytest tests` run stops during collection because the pre-existing module FG/03_chunking/legal_section_chunker.py is absent. This affects tests/test_legal_section_chunker.py and tests/test_reference_retriever.py and is unrelated to this feature. Those two tests were excluded from the 127-test regression run; they were not reported as passing.
- Ruff is not installed in the selected Python environment, so no Ruff result is claimed. `git diff --check`, JavaScript syntax, Python compilation, and the test suites above were used instead.

Live-source limitations:
- The bounded live smoke deliberately covered only the public SCI RTI adapter path. CI tests use mocked official-source responses and do not depend on mutable government websites.
- CAPTCHA, authenticated/private RTI records, robots-restricted searches, and unsupported JavaScript-only pages remain unavailable by design. No bypass was attempted.
- A successful page retrieval proves only that the adapter and extractor can safely retrieve that official page. It is not evidence for an RTI fact unless the deterministic evidence validator also accepts a matched passage.
~~~
