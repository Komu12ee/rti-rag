# RTI Assistant: Gap Analysis to an Industry-Standard System

## Bottom line

RTI Assistant is an advanced prototype / early MVP, not an industry-standard production system. The retrieval logic and legal-domain features are real; the production gaps are mainly durability, security boundaries, measurable quality, and operability.

This assessment is based on the current working tree. It is a code and configuration audit, not a completed production-load or full-test-suite certification.

| Dimension | Where the project is now | Google-caliber version | Specific gap | Difficulty to close |
| --- | --- | --- | --- | --- |
| Architecture & scalability | Query retrieval fans out across up to four collections concurrently. PDF upload performs OCR and the three-call PIO workflow synchronously inside the Flask request, with a 300-second subprocess timeout. Auth, advisory cache, and model/client state are process-local. PM2 config is one local-development instance. | Stateless API replicas behind a load balancer; uploads go to object storage, then a queue; durable workers perform OCR/indexing; job state is in Postgres; Redis handles cache/session/rate limit; managed/remote vector DB is replicated and backed up. | One slow PDF ties up a web worker; a restart loses sessions/cache; horizontal replicas would have inconsistent auth/advisory state; there is no durable job lifecycle or autoscaling topology. | High — about one week for a credible queue/job implementation; several months for mature scale operations. |
| Reliability & failure handling | There are useful local safeguards: typed PDF/OCR errors, file-signature validation, a 25MB upload cap, Qdrant retry for a stale local lock, per-collection failure tolerance, and a narrow LLM retry for one empty Sarvam length-stop case. | Explicit time budgets per dependency, retries with exponential backoff/jitter only for safe failures, circuit breakers, idempotency keys, dead-letter queues, degradation policies, and recovery/replay tooling. | Most exceptions become a user-visible error string. No circuit breaker, no durable retry state, no DLQ, no resumption after worker crash, and no defined behavior when retrieval is partially unavailable. | Medium-high — 3–5 days for request policies; about one week with durable jobs/replay. |
| Evaluation & quality assurance | There are behavior and security tests, especially for the Section 4 verifier. There is no corpus-level retrieval benchmark, labelled relevance set, answer-faithfulness measurement, hallucination metric, or release threshold for the RAG/PIO answer path. | Versioned evaluation dataset with query-to-relevant-passage/case labels; Recall@K, MRR/nDCG, citation correctness, groundedness, refusal/abstention accuracy, latency, and regression gates. Human adjudication for legal outputs. | “It seems good on examples” is not a quality system. The project cannot quantify whether a chunking, embedding, prompt, or fusion change improved or degraded legal answers. | Medium — 4–6 focused days gets a credible first harness. |
| Security & government-data handling | Positive controls exist: PIO routes require a PIO role, citizen passwords use PBKDF2, filenames are sanitized, PDF magic bytes are checked, and the Section 4 web retriever has strong SSRF protections. | One identity system, DB-backed users/roles/sessions, MFA/SSO where appropriate, API rate limits, audit logs, encrypted storage, least-privilege service accounts, retention/deletion policies, threat modelling, and security review. | Flask uses JSON files for accounts and in-memory bearer sessions; sessions vanish on restart and do not share across replicas. Manual PIO users still permit a plaintext-password fallback. There is no visible API rate limiting. Raw uploaded PDFs and extracted text persist under the application upload directory without an observed retention cleanup path. | High priority, medium effort — 3–5 days for the dangerous basics; ongoing for governance/compliance. |
| Observability | There are `print`-based stage timings, request-duration prints, Node request logging, and launcher health polling. | Structured JSON logs with request/job IDs, RED metrics, tracing across API → worker → OCR → vector DB → LLM, dashboards, SLOs, alerts, and privacy-safe log controls. | At 2am, an operator can inspect server logs but cannot reliably attribute failures, regressions, or cost spikes to a request, user, model, vector collection, or deployment. | Medium — 2–4 days for a useful baseline. |
| Code quality & testing | The repository has visible Python test modules across root and Web UI areas, including security, cache/rate-limit, OCR, routing, and PIO tests. Several services have clear functional separation. | Reproducible builds, locked dependencies, test tiers, isolated integration environments, coverage trends, lint/type checks enforced in CI, code ownership/review, migration discipline, and deploy gates. | The tracked GitHub workflow only invokes an opaque self-hosted deployment script; it does not run tests, linting, or type checking. Requirements are largely broad `>=` ranges and contain conflicting Pydantic ranges. The Flask app is a large orchestration file with dynamic imports and duplicated imports. | Medium — 3–5 days for lockfiles plus CI quality gates; refactoring is incremental. |
| Cost & efficiency | Models are lazy-loaded; retrieval candidates, case expansion, and context size are capped; reranking is disabled because of latency; the offline preprocessing manifest hashes PDFs to prevent duplicate corpus work. | Per-stage cost accounting; content-addressed idempotency; cached query embeddings/retrievals; batching; tiered models; token/context budgets; policy-driven reranking; capacity planning. | The upload path invokes preprocessing with `--force`, bypassing normal manifest dedupe; a repeat upload repeats OCR. New PIO uploads run a three-call workflow without an API-level idempotency key. Advisory caching is process-local rather than shared. | Medium — 3–4 days for idempotency/cache metrics and targeted caching. |

## Evidence-backed findings

The project is not merely API stitching. Hybrid dense/sparse retrieval, reciprocal-rank fusion, collection balancing, precedent case expansion, document hashing, OCR routing, and source-aware answer constraints are substantive engineering.

However, production claims would fail scrutiny because:

- `FG/05_webui/app.py` runs OCR preprocessing synchronously through `subprocess.run`, blocking the request during document work.
- The same Flask module stores accounts in local JSON files and retains bearer sessions in process memory.
- Manual PIO users retain a plaintext-password compatibility path.
- `FG/04_embeddings_and_kg/scripts/rag_pipeline.py` has a timeout and narrow retry, but no general provider resilience policy.
- `.github/workflows/deploy.yml` deploys through a self-hosted script without a visible test/build gate.
- `requirements.txt` is not a reproducible production dependency lock.

## Prioritized four-week punch list

The first five items have the best impact-to-effort ratio for both risk reduction and interview credibility.

1. **Build a RAG evaluation harness** — 4–6 days  
   Create 75–100 representative Hindi/English RTI queries with expected source chunks/cases and answer rubrics. Report Recall@5, MRR, citation validity, abstention correctness, groundedness, p50/p95 latency, and cost/query. Run it before every retrieval or prompt change.

2. **Make uploads asynchronous and durable** — 5 days  
   Add `upload`, `processing_job`, and `document` records in Postgres; send OCR/PIO work to a worker queue; expose job status/progress; make retries idempotent by PDF SHA-256. This removes the 300-second web-request failure mode.

3. **Close the highest-risk security holes** — 3–4 days  
   Remove the plaintext PIO-password fallback, stop using JSON files/in-memory sessions for deployed auth, add per-IP and per-user request limits, and add explicit upload-retention deletion. Make PIO authorization fail closed.

4. **Add production-grade telemetry basics** — 2–3 days  
   Emit structured logs with request ID, user/job ID, route, dependency, latency, error class, and model/vector collection. Add metrics for LLM failures, OCR failures, Qdrant latency, queue depth, and answer latency. Alert on error-rate and queue-age thresholds.

5. **Turn deployment into a quality gate** — 2–3 days  
   Add a locked dependency file, CI that runs formatting, lint/type checks, unit tests, and a small integration/evaluation smoke test. Deploy only after the gate passes; retain deployment version and rollback instructions.

6. **Add cost controls and idempotency** — 2–3 days  
   Cache PDF preprocessing by SHA-256, cache query embeddings and short-lived retrieval results, record tokens/latency per provider call, and route easy factual queries to the cheaper path. Remove `--force` for duplicate user uploads unless a reprocess is requested.

7. **Containerize the runtime and externalize state** — 4–5 days  
   Produce Docker images for API/worker, use remote Qdrant plus managed Postgres/Redis, and document health/readiness, backup, restore, and reindex flows. This is the clearest bridge from “works on my VM” to a deployable service.

## Recommended scope for a four-week implementation

If only five items can be completed, implement items 1–5. This would not make the system Google-scale, but it would truthfully move the project from a sophisticated student RAG application to a measured, secure, operable MVP with a credible production path.
