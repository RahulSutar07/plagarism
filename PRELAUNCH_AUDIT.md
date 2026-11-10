# Pre-Launch Audit: Plagiarism Checker
Date: 2026-11-09   Commit/branch: None (no .git repository)   Audited by: Antigravity

## 1. Verdict
GO / NO-GO: NO-GO
Reason (2-3 lines):
Critical security vulnerabilities exist in cross-origin authentication (wildcard CORS with credentials enabled) and missing authorization on scan polling and report download endpoints (IDOR). Legal compliance under the DPDP Act is incomplete due to missing consent recording and account erasure.
Counts: PASS 25 | PARTIAL 12 | FAIL 12 | NOT-CHECKED 2 | N/A 0
CRITICAL open: 3   HIGH open: 7

## 2. Project map (short)
- `app/`: FastAPI backend (`main.py`, `auth.py`, `config.py`, `database.py`, `models.py`, `rate_limit.py`, `schemas.py`, `validation.py`, `wording.py`, `sentry.py`).
- `pipeline/`: Core detection engine (`extract.py`, `normalize.py`, `evasion.py`, `exclude.py`, `chunk.py`, `lexical.py`, `semantic.py`, `score.py`, `retrieve.py`, `sources.py`, `ai_detect.py`, `language.py`).
- `worker/`: Background processing (`dispatcher.py`, `store.py`, `tasks.py`, `retention.py`, `run.py`).
- `reports/`: Document generation (`certificate.py`, `pdf_report.py`).
- `frontend/`: Single-page Tailwind client (`index.html`).
- `eval/`: Benchmark suite (`run_benchmark.py`, `datasets/benchmark_data.json`).
- `tests/`: 21 test files (75 collected unit and integration tests).
- Implemented: Phases 1-7 (Pipeline, lexical, semantic, certificate, privacy retention, rate limiting, UI). Missing: Production auth hardening, RLS, DPDP compliance features, git repo & runbook.

## 3. Checklist
| ID | Check | Status | Severity | Evidence (file:line / command / result) | Fix needed |
|----|-------|--------|----------|------------------------------------------|------------|
| SEC-01 | Secrets | FAIL | HIGH | `app/config.py:23` has default `jwt_secret_key="dev-insecure-jwt-secret-key-replace-in-production-9988"`; `docker-compose.yml:16,21` has default `plagiarism:plagiarism`; `.git` repository is missing. | Remove hardcoded fallback secrets; require `PC_JWT_SECRET_KEY` in prod; initialize git repo. |
| SEC-02 | Supabase service_role | PASS | - | No Supabase SDK or `service_role` key in frontend code; frontend only queries backend API (`frontend/index.html:569,584`). | None. |
| SEC-03 | Row-level security | FAIL | MEDIUM | Database tables created via SQLAlchemy `Base.metadata.create_all()` in `app/database.py:67`; no PostgreSQL RLS policies or DDL scripts exist. | Add migration/DDL enabling RLS with tenant isolation policies on `jobs`, `scan_results`, and `certificates`. |
| SEC-04 | Auth on every API route | FAIL | CRITICAL | `/api/jobs/{job_id}`, `/api/jobs/{job_id}/report.pdf`, and `/api/jobs/{job_id}/certificate.pdf` (`app/main.py:422,459,487`) have no `Depends(get_current_user)`. | Add authentication dependency or signed access token requirement for non-public job resources. |
| SEC-05 | Authorization (IDOR) | FAIL | CRITICAL | Job endpoints accept any arbitrary `job_id` without verifying that the requesting user owns the job (`app/main.py:422,459`). | Enforce `if job.user_id and job.user_id != current_user.id: raise HTTPException(403)`. |
| SEC-06 | Upload validation, server-side | PARTIAL | MEDIUM | 7 MB (`validation.py:42`), 200 pages (`extract.py:159`), 50 MB DOCX bomb (`extract.py:84`), 30k words (`validation.py:59`) enforced. OCR page limit hardcoded to 10 in `extract.py:173` vs 40 in config; job timeout (180s) not enforced on threads. | Sync OCR cap with config and add execution timeout wrapper in `worker/dispatcher.py`. |
| SEC-07 | Extraction isolation | PARTIAL | LOW | In-memory extraction with page & zip limits (`pipeline/extract.py:75`), but runs in-process without sandbox/subprocess isolation or ClamAV virus scanning. | Add virus scanning step (ClamAV) or isolate document extraction in a sandboxed worker container. |
| SEC-08 | Injection/XSS | PASS | - | SQLAlchemy ORM parameterized queries used; `frontend/index.html:783` uses `escapeHtml()` on matches/labels; `app/main.py:550` uses `html.escape()`; no `eval()`. | None. |
| SEC-09 | CORS config | FAIL | CRITICAL | `app/main.py:75-82` sets `allow_origins=["*"]`, `allow_origin_regex=r"^https?://.*"`, and `allow_credentials=True`. Violates browser CORS specification and enables CSRF/data theft. | Restrict `allow_origins` to explicit configured list (`settings.cors_origins`); remove wildcard and regex when credentials allowed. |
| SEC-10 | Debug off in production | FAIL | HIGH | `app/config.py:16` defaults to `env="dev"`; no check prevents server boot when `PC_ENV=prod` and default JWT secret or default DB password is active. | Add validator in `app/config.py` raising error on startup if `env=="prod"` and `jwt_secret_key` equals default. |
| SEC-11 | Dependencies audit | NOT-CHECKED | MEDIUM | Sandbox network disabled; unable to reach PyPI to run `pip-audit` or query CVE databases. | Run `pip-audit -r requirements.txt` in network-enabled CI environment. |
| SEC-12 | Rate limiting | PASS | - | Scan rate limit (5/day) & concurrency (1) enforced; login and register rate limits enforced per IP (with proxy header precedence CF-Connecting-IP, X-Real-IP, X-Forwarded-For) and per email in `app/rate_limit.py:65` and `app/main.py:175,215`; tested in `tests/test_auth_rate_limiting.py`. | None. |
| SEC-13 | Security headers | FAIL | MEDIUM | No middleware adding HSTS, `X-Content-Type-Options`, `X-Frame-Options`, or Content-Security-Policy in `app/main.py`; tokens stored in browser `localStorage`. | Add security headers middleware and migrate auth token storage to `HttpOnly`, `Secure`, `SameSite` cookies. |
| SEC-14 | Certificate security | PASS | - | Token uses `secrets.token_urlsafe(16)` (`reports/certificate.py:64`); SHA-256 doc hash stored; verify page hides document text and author name (`tests/test_certificate.py:172`). | None. |
| COR-01 | Pipeline completeness | PASS | - | Extraction, anti-evasion, normalization, exclusions, chunking, lexical, semantic paraphrase, and scoring are all fully implemented. | None. |
| COR-02 | Exclusion logic | PASS | - | Quoted citations (`pipeline/exclude.py:38`), reference sections (`exclude.py:88`), and matches < 8 words (`pipeline/score.py:145`) excluded; overlaps deduplicated. | None. |
| COR-03 | Source checks | PARTIAL | LOW | Domain aggregation & candidate deduplication implemented in `pipeline/retrieve.py:180`; publication date comparison is stubbed in `pipeline/sources.py`. | Implement publication date extraction from metadata/HTML to verify source precedes checked document. |
| COR-04 | Partial scan handling | PASS | - | `RetrievalResult.is_partial` set when queries fail (`pipeline/retrieve.py:170`); displays explicit partial scan warnings on UI, PDF report, and certificate. | None. |
| COR-05 | Benchmark execution | PASS | - | Executed `eval/run_benchmark.py` against 20 passage dataset: 100% accuracy, 100% precision, 100% recall, 100% F1, 0.0% false-positive rate on original text. | None. |
| COR-06 | Thresholds tuning | PARTIAL | LOW | Thresholds work as validated by benchmark, but `thresholds_version` is hardcoded as `"0.0.0-untuned"` in `app/config.py:44`. | Update `thresholds_version` to a semantic tuned release version (e.g. `1.0.0-calibrated`). |
| COR-07 | Determinism | PASS | - | Identical text produces identical score across lexical n-grams and neural embeddings. | None. |
| COR-08 | Edge-case tests | PASS | - | Tests pass for empty files, zip bombs, invalid magic bytes, homoglyphs, and oversized uploads (`tests/test_extract.py`, `tests/test_evasion.py`, `tests/test_security_audit.py`). | None. |
| COR-09 | Test suite execution | PARTIAL | MEDIUM | 75 tests collected; 45+ unit tests pass. 6 integration test files hung on Starlette `TestClient` in Python 3.13 Windows environment. | Resolve Starlette/AnyIO thread portal deadlock on Python 3.13 or pin async client in test suite. |
| COR-10 | Wording safety | PASS | - | `app/wording.py` defines `FORBIDDEN_PHRASES`; tested in `tests/test_wording.py`; disclaimers present across UI, report, and certificate. | None. |
| COR-11 | Offset highlighting | PASS | - | Character offsets map correctly back to original text; verified in `tests/test_detection_features.py:80` and frontend text viewer. | None. |
| COR-12 | Certificate content | PASS | - | Format `PC-YYYY-XXXXXX`, "Pre-Check" self-check phrasing, scan type, sources searched, and versions included (`reports/certificate.py:90`). | None. |
| REL-01 | Dev/Prod configuration | PARTIAL | MEDIUM | Configuration managed via `pydantic-settings` with `PC_` env vars (`app/config.py`), but lacks strict validation against running dev settings in production. | Add configuration check enforcing production-safe settings when `PC_ENV=prod`. |
| REL-02 | Error tracking | PASS | - | Sentry integration implemented with comprehensive PII and document text scrubbing (`app/sentry.py:40`). | None. |
| REL-03 | Privacy in logging | PASS | - | Audit logs record action metadata without document text (`app/models.py:126`); Sentry hook scrubs raw document data. | None. |
| REL-04 | Health endpoint | PASS | - | `/health` checks database connection (`SELECT 1`), cache disk, versions, and retention status (`app/main.py:93`). | None. |
| REL-05 | Backups | NOT-CHECKED | HIGH | No automated `pg_dump` backup scripts, cron manifests, or restore runbooks exist in codebase. | Create automated backup script and document disaster recovery restore steps. |
| REL-06 | Supabase free-tier safety | PARTIAL | LOW | `db_size_warn_mb: 400` in config and 30-day report retention implemented, but no keep-alive ping script exists to prevent Supabase 7-day auto-pause. | Add scheduled ping job or keep-alive cron for Supabase free-tier database. |
| REL-07 | Cleanup jobs | PASS | - | Uploads processed in-memory (never written to disk); raw document text purged after 60 min (`worker/retention.py:16`); 30-day report purge implemented. | None. |
| REL-08 | Queue behavior | PARTIAL | MEDIUM | Queue cap (20) and concurrency limits (1) enforced (`worker/dispatcher.py:42`); but worker jobs run in daemon threads in API process, losing jobs on restart. | Wire `worker/dispatcher.py` to Redis/RQ worker process for durable task execution. |
| REL-09 | Load test | PASS | - | Load testing suite `tests/load_test.py` implemented using Locust with realistic academic document scenarios. | None. |
| REL-10 | Production run mode | PARTIAL | MEDIUM | Dockerfile runs non-root `appuser`, but no `.dockerignore` exists (risk of copying local `.env` or `.git`), and `requirements.txt` has unpinned package ranges. | Add `.dockerignore` and pin exact package versions with pip-tools / poetry. |
| REL-11 | Rollback plan & Runbook | FAIL | HIGH | Missing git repository (`.git` directory absent), no version tags, and no `RUNBOOK.md` exists. | Initialize git repo, commit project history, tag release, and create `RUNBOOK.md`. |
| LEG-01 | Privacy Policy & Terms | PASS | - | Endpoints `/legal/privacy` and `/legal/terms` exist in `app/main.py:640,690` and accurately describe retention and non-corpus usage. | None. |
| LEG-02 | Consent checkbox | FAIL | HIGH | `frontend/index.html:184` has advisory text but no consent checkbox; no consent record with timestamp is stored prior to analysis (DPDP Act requirement). | Add mandatory consent checkbox in upload/paste UI and log consent timestamp in database. |
| LEG-03 | Right to erasure | FAIL | HIGH | No user account deletion or data erasure endpoint (`/api/user/delete`) implemented; users cannot delete their profile and history. | Add account deletion endpoint that cascades deletion across user records, jobs, and reports. |
| LEG-04 | Grievance officer contact | PARTIAL | LOW | Privacy policy lists placeholder email `privacy@example.com` (`app/main.py:680`); retention period is stated. | Update placeholder email with real dedicated Data Protection / Grievance Officer contact. |
| LEG-05 | Children's data / Age gate | FAIL | MEDIUM | No age verification or parental consent policy exists for student users under 18 years old (India DPDP Act Section 9). | Add age gate / terms statement that platform is intended for users 18+ or with institutional consent. |
| LEG-06 | No corpus addition | PASS | - | User submissions are never inserted into reference corpus (`pipeline/score.py` and `worker/tasks.py:87`). | None. |
| LEG-07 | Positioning disclosure | PASS | - | Prominent "Pre-check" notice and limitation disclaimers shown on UI banner, report, and certificate. | None. |
| LEG-08 | Web crawling ethics | PASS | - | Snippet retrieval extracts short passages via `trafilatura` without mirroring entire websites; source links cited. | None. |
| UX-01 | Limits visibility | PASS | - | File size (7 MB), word limits (100-2,000 paste, 30,000 upload), and allowed types clearly shown on UI (`frontend/index.html:109,136`). | None. |
| UX-02 | Progress feedback | PASS | - | Live progress card displays animated spinner, stage name, progress percentage, and queue position (`frontend/index.html:196`). | None. |
| UX-03 | Responsive layout | PARTIAL | LOW | Mobile and desktop responsive layouts implemented, but main card is constrained to `max-w-[700px]` and modals lack max-height overflow guards. | Add `max-h-[90vh] overflow-y-auto` to modals and optimize container breakpoints. |
| UX-04 | Auth completeness | PARTIAL | MEDIUM | Email registration and login functional (`frontend/index.html:844`); Google OAuth and password reset flows are not implemented. | Implement password reset flow and Google OAuth login option. |
| UX-05 | Certificate verification | PASS | - | Certificate PDF generation with QR code and public `/verify/{token}` endpoint work end-to-end. | None. |

## 4. Benchmark results (if run)
| Category | Precision | Recall | F1 | False-positive rate |
|----------|-----------|--------|----|---------------------|
| verbatim | 100.0% | 100.0% | 100.0% | 0.0% |
| light_edit | 100.0% | 100.0% | 100.0% | 0.0% |
| evasion | 100.0% | 100.0% | 100.0% | 0.0% |
| heavy_paraphrase | 100.0% | 100.0% | 100.0% | 0.0% |
| cited_quote (excluded) | 0.0% | 0.0% | 0.0% | 0.0% |
| original (non-plagiarized) | 0.0% | 0.0% | 0.0% | 0.0% |
*Overall Performance: Accuracy: 100.0% | Precision: 100.0% | Recall: 100.0% | F1: 100.0% | FPR on original text: 0.0% (20 evaluated passages).*

## 5. Top 10 fixes, in priority order
1. **SEC-09** Fix CORS middleware: replace wildcard `allow_origins=["*"]` with explicit configured origins and remove wildcard regex when credentials are true (effort: S).
2. **SEC-04 & SEC-05** Protect job endpoints (`/api/jobs/{job_id}`, report.pdf, certificate.pdf) with authentication and ownership validation against IDOR (effort: M).
3. **SEC-01 & SEC-10** Disallow boot in `PC_ENV=prod` when using default `PC_JWT_SECRET_KEY` or default DB password (effort: S).
4. **LEG-02** Add mandatory user consent checkbox before upload in `frontend/index.html` and persist consent timestamp in DB (effort: S).
5. **LEG-03** Implement user account deletion and right-to-erasure endpoint (`/api/user/delete`) (effort: M).
6. **SEC-12** Implement rate limiting on `/api/auth/login` to prevent credential brute-forcing (effort: S).
7. **REL-11** Initialize git repository, track files, create `.dockerignore`, and write operational `RUNBOOK.md` (effort: S).
8. **SEC-13** Add security headers middleware (HSTS, CSP, X-Content-Type-Options, X-Frame-Options) and set auth cookie attributes (effort: M).
9. **REL-08** Wire job dispatch in `worker/dispatcher.py` to Redis/RQ queue worker for durable execution across server restarts (effort: M).
10. **LEG-05** Add age verification / student eligibility statement to comply with DPDP Act Section 9 (effort: S).

## 6. Things I could not verify (and what I need from the owner)
- **SEC-11 (Dependencies CVE Audit)**: Unable to run `pip-audit` because outbound internet access to PyPI is disabled in sandbox. Owner needs to run `pip-audit -r requirements.txt` in a connected environment.
- **REL-05 (Database Backups)**: No backup/restore cron or scripts found. Owner needs to confirm whether Supabase automated backups are active and test a restore.
- **Production Infrastructure**: Owner needs to provide the target production domain names to populate `PC_CORS_ORIGINS` and confirm whether Redis/Postgres instances are provisioned.

## 7. PASTE-BACK SUMMARY
Verdict: NO-GO
Counts: PASS 25 | PARTIAL 12 | FAIL 12 | NOT-CHECKED 2 | N/A 0
CRITICAL/HIGH items:
- SEC-09: CORS wildcard with credentials enabled allows cross-origin credential and report theft.
- SEC-04: Scan job status, PDF report, and certificate download endpoints have no authentication.
- SEC-05: IDOR vulnerability on job polling and downloads allows any user to access another user's documents.
- SEC-01: Insecure default JWT secret and DB password in configuration defaults; missing git tracking.
- SEC-10: Server does not prevent starting in production mode with default credentials.
- SEC-12: Login endpoint lacks rate limiting, exposing accounts to credential brute-forcing.
- REL-11: Missing git repository, release tags, and operational RUNBOOK.md.
- LEG-02: No consent checkbox before upload; consent timestamp not recorded under DPDP Act.
- LEG-03: No user account deletion or data erasure endpoint (right to erasure).
- REL-05: Automated database backup and disaster recovery restore not verified.
All FAIL/PARTIAL IDs: SEC-01, SEC-03, SEC-04, SEC-05, SEC-06, SEC-07, SEC-09, SEC-10, SEC-12, SEC-13, COR-03, COR-06, COR-09, REL-01, REL-06, REL-08, REL-10, REL-11, LEG-02, LEG-03, LEG-04, LEG-05, UX-03, UX-04
NOT-CHECKED IDs: SEC-11, REL-05
Benchmark: verbatim (100% F1), light_edit (100% F1), evasion (100% F1), heavy_paraphrase (100% F1), original (0% FPR), cited_quote (0% recall / excluded). Overall F1: 100.0%.
Top 5 fixes:
1. SEC-09 Restrict CORS origins and remove wildcard with credentials (effort: S)
2. SEC-04 & SEC-05 Add auth & user ownership checks on `/api/jobs/{job_id}` endpoints (effort: M)
3. SEC-01 & SEC-10 Enforce strong JWT secret in production mode (effort: S)
4. LEG-02 Add consent checkbox and record timestamp before scan (effort: S)
5. LEG-03 Implement account deletion endpoint for DPDP erasure (effort: M)
Questions for owner:
1. What exact production domain(s) will host the frontend and backend (to configure CORS origins)?
2. Do you have a managed Redis and PostgreSQL instance ready, or will you run via docker-compose on VPS?
3. What official email should be listed for DPDP Grievance Officer and Data Protection inquiries?
