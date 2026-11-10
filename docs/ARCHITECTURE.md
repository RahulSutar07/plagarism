# Plagiarism Pre-Check - Architecture & Engineering Specification

## 1. Executive Summary

**Plagiarism Pre-Check** is a high-throughput, enterprise-ready asynchronous plagiarism detection engine designed to identify verbatim overlap, near-duplicate text, and subtle paraphrasing against local corpora and open-web sources.

Engineered for academic institutions, ed-tech platforms, and commercial publishers, the system strictly positions itself as an **academic pre-check**, avoiding deceptive guarantees ("100% original") and punitive terminology ("guilty", "failed"). The architecture enforces **strict data minimization**, guaranteeing that user manuscripts are processed in memory and never retained on disk or permanently in databases.

---

## 2. High-Level Architecture

```
                  +----------------------------------------------+
                  |         Client Web Browser / API Client      |
                  +----------------------------------------------+
                                         |
                                         | HTTPS (TLS 1.3)
                                         v
                  +----------------------------------------------+
                  |           Nginx / Reverse Proxy              |
                  +----------------------------------------------+
                                         |
                     +-------------------+-------------------+
                     |                                       |
                     v                                       v
         +-----------------------+               +-----------------------+
         |     FastAPI App       |               |     FastAPI App       |
         |    (Instance 1)       |               |    (Instance 2)       |
         +-----------------------+               +-----------------------+
                     |                                       |
         +-----------+---------------------------------------+-----------+
         |                                                               |
         v                                                               v
+------------------+                                            +------------------+
| PostgreSQL / DB  | <--- SQLAlchemy 2.0                        |  Redis 7 / Queue | <--- Job Dispatcher
| (Users, Metadata,|      (Transparent SQLite Fallback)         |  (Stream / Queue |      (FIFO Queue)
| Certs, Audits)   |                                            |   with In-Memory)|
+------------------+                                            +------------------+
                                                                         |
                                         +-------------------------------+-------------------------------+
                                         |                                                               |
                                         v                                                               v
                         +-------------------------------+                               +-------------------------------+
                         |      Worker: Fast Queue       |                               |      Worker: Deep/OCR Queue   |
                         |  (Normal Text, DOCX, Fast PDF)|                               |  (Scanned PDFs, Paraphrasing) |
                         +-------------------------------+                               +-------------------------------+
                                         |                                                               |
                                         +-------------------------------+-------------------------------+
                                                                         |
                                                                         v
                                                        +---------------------------------+
                                                        |     4-Stage Analysis Pipeline   |
                                                        |  1. Ingestion & Sanitization    |
                                                        |  2. Exclusions & Tokenization   |
                                                        |  3. Lexical Winnowing (Fingerpr)|
                                                        |  4. Semantic Bi-Encoder Scoring |
                                                        +---------------------------------+
```

---

## 3. Four-Stage Analysis Pipeline

### Stage 1: Ingestion & Evasion Defense (`pipeline/extract.py`, `pipeline/evasion.py`)
- **Memory-First Streaming**: Uploaded files (`.pdf`, `.docx`, `.txt`) are parsed directly from RAM bytes into raw text. No temporary files are written to `/tmp` or disk.
- **Magic Byte Verification**: Verifies binary headers (`%PDF-` for PDF, `PK\x03\x04` for DOCX). Mismatched or spoofed extensions are rejected with HTTP 400.
- **Zip-Bomb Decompression Guard**: DOCX parsing strictly tracks cumulative uncompressed stream size against a 30 MB ceiling, halting decompression bombs before memory exhaustion.
- **Homoglyph & Zero-Width Sanitization**: 
  - Canonicalizes Cyrillic/Greek lookalikes (`а`, `е`, `о`, `р`) to Latin counterparts using unicode confusable tables.
  - Strips zero-width non-joiners (`\u200B`, `\u200C`, `\u200D`, `\uFEFF`) and soft hyphens inserted to break word boundaries.
  - Normalizes full-width and non-breaking white spaces.
  - Flags evasion attempts in the audit trail without crashing the pipeline.

### Stage 2: Normalization & Structural Exclusions (`pipeline/normalize.py`, `pipeline/exclude.py`)
- **Citation & Bibliography Masking**:
  - Automatically identifies references, bibliography, and works-cited sections via structural regex heading anchors.
  - Replaces reference lists and in-text parenthetical citations (e.g., `(Smith et al., 2021)`, `[12-14]`) with sentinel tokens, preventing false-positive similarity spikes on academic attribution.
- **Quotation Handling**:
  - Recognizes quoted spans enclosed in typographic, standard double, and single quotes.
  - Segregates quotes for optional exclusion or differentiated reporting.
- **Lexical Canonicalization**:
  - Unicode NFKD normalization, lowercasing, punctuation stripping, and whitespace collapse.

### Stage 3: Lexical Matching via Winnowing (`pipeline/chunk.py`, `pipeline/lexical.py`)
- **Word-Level N-Grams**: Extracts rolling $n$-grams ($n=5$ words by default).
- **Winnowing Algorithm**:
  - Applies rolling polynomial hashing over $n$-grams.
  - Selects minimum hash values within a sliding window of size $w$ ($w=4$).
  - Guarantees detection of contiguous substrings of length $\ge n + w - 1$ while producing a compact fingerprint index.
- **Candidate Retrieval**:
  - Compares query fingerprints against inverted index postings (`index/corpus.py`).
  - Merges adjacent match spans separated by small gaps into contiguous matches.
  - Categorizes matches into **Exact** ($100\%$ token match) and **Near** (minor substitutions or deletions).

### Stage 4: Semantic Paraphrase Detection (`pipeline/semantic.py`, `pipeline/score.py`)
- **Sentence Chunking**: Splits query text and candidate source documents into overlapping sentence windows.
- **Bi-Encoder Dense Retrieval**:
  - Leverages Sentence-Transformers (`all-MiniLM-L6-v2`) to produce 384-dimensional dense embeddings.
  - Computes cosine similarity matrices across query chunks and candidate sources.
  - Matches with cosine similarity $\ge 0.82$ that lack lexical verbatim overlap are classified as **Paraphrased Plagiarism**.
- **Composite Scoring**:
  - Calculates non-overlapping union of matched word tokens to avoid double-counting.
  - Categorizes similarity into Exact, Near, and Paraphrased percentages.

---

## 4. Strict Data Minimization & Privacy Architecture

The platform complies with GDPR Article 5(1)(c) and academic integrity privacy standards:

1. **Zero Raw Text on Disk**: Uploaded files exist only in memory during extraction.
2. **In-Memory Worker Dispatch**: Raw document text is held in worker memory only for the duration of the scan.
3. **1-Hour Raw Text Purge (`worker/retention.py`)**:
   - Following scan completion, the raw document text stored in the database is automatically set to `NULL` after 60 minutes (`purge_expired_raw_texts`).
   - The document's cryptographic SHA-256 integrity hash is retained so users can verify document authorship without exposing the document text.
4. **30-Day Metadata Sunset**: Scan metadata and certificates are purged after 30 days unless extended by enterprise policy.
5. **PII Scrubbing in Telemetry (`app/sentry.py`)**:
   - Sentry event filters scrub passwords, authorization headers, IP addresses, document titles, and any raw document text from error stack traces.

---

## 5. Asynchronous Job & Worker Queue Architecture

Plagiarism analysis is strictly decoupled from the synchronous HTTP request cycle:

1. **Client Submission**:
   - `POST /api/check/upload` or `POST /api/check/paste` validates input and returns HTTP 202 Accepted with a unique `job_id`, initial queue position, and estimated wait time.
2. **Job Store (`worker/store.py`)**:
   - Thread-safe storage with support for Redis backend or in-memory fallback.
   - Enforces a maximum queue capacity (`max_queued = 100`) to prevent denial-of-service memory exhaustion.
3. **Worker Pools (`worker/dispatcher.py`)**:
   - Fast Worker: Handles text pastes, lightweight DOCX, and search.
   - OCR/Deep Worker: Handles multi-page PDFs and heavy neural embedding inference.
   - Progress tracking (`0% -> 100%`) through discreet stages: `extracting`, `sanitizing`, `retrieving`, `matching`, `completed`.
4. **Polling / SSE**:
   - Clients poll `GET /api/jobs/{job_id}` until status reaches `completed`.

---

## 6. Database Schema Design (`app/models.py`)

The database layer utilizes SQLAlchemy 2.0 with automatic migration support and seamless fallback to SQLite for local development:

```
+--------------------+       1:N       +--------------------+
|       User         | --------------< |       Job          |
+--------------------+                 +--------------------+
| id (UUID / Int PK) |                 | id (String PK)     |
| email (Unique)     |                 | user_id (FK Null)  |
| hashed_password    |                 | status (Enum)      |
| role ('user','adm')|                 | stage (Enum)       |
| tier ('free','pro')|                 | progress_pct (Int) |
| created_at (UTC)   |                 | created_at (UTC)   |
+--------------------+                 +--------------------+
                                                 | 1:1
                                                 v
                                       +--------------------+
                                       |    ScanResult      |
                                       +--------------------+
                                       | id (Int PK)        |
                                       | job_id (FK Unique) |
                                       | overall_sim (Float)|
                                       | exact_pct (Float)  |
                                       | near_pct (Float)   |
                                       | paraphrase_pct     |
                                       | total_words (Int)  |
                                       | doc_hash (SHA-256) |
                                       | raw_text (Nullable)| <--- Set to NULL after 1 hr
                                       +--------------------+
                                                 | 1:1
                                                 v
                                       +--------------------+
                                       |    Certificate     |
                                       +--------------------+
                                       | id (Int PK)        |
                                       | job_id (FK Unique) |
                                       | certificate_id     | <--- "PC-YYYY-XXXXXX"
                                       | token (UUID4)      | <--- Secret verification token
                                       | doc_hash (SHA-256) |
                                       | created_at (UTC)   |
                                       +--------------------+
```

---

## 7. Security & Defense Matrix

| Vulnerability Vector | Defense Mechanism | File Implementation |
|---|---|---|
| **Decompression Bomb (Zip Bomb)** | DOCX uncompressed size tracked against 30MB threshold | `pipeline/extract.py` |
| **Spoofed MIME / Extension** | Binary magic-byte inspection (`%PDF-`, `PK\x03\x04`) | `app/validation.py` |
| **Cross-Site Scripting (XSS)** | Full HTML entity escaping (`html.escape`) in public views | `app/main.py` |
| **SQL Injection** | Parameterized SQLAlchemy 2.0 ORM expressions | `app/models.py`, `app/database.py` |
| **Denial of Service (DoS)** | Salted IP rate limiting (5 scans/day) & 1 concurrent scan lock | `app/rate_limit.py` |
| **Memory Exhaustion (OOM)** | Queue capacity bounded at 100 jobs with HTTP 503 backpressure | `worker/store.py` |
| **Data Leakage in Errors** | Generic client error messages with zero raw text reflection | `app/main.py`, `tests/test_security_audit.py` |
