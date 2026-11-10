# Plagiarism‑Checker

A FastAPI based service that analyses uploaded documents for plagiarism, stores scan results, and provides verification certificates.

---

## Table of Contents
- [Setup](#setup)
- [Environment Variables](#environment-variables)
- [Running the Application](#running-the-application)
- [Running Tests](#running-tests)
- [Running the Benchmark](#running-the-benchmark)
- [Project Structure Overview](#project-structure-overview)
- [Known Limitations & Untested Areas](#known-limitations--untested-areas)

---

## Setup

1. **Clone the repository** (if you haven't already):

   ```powershell
   git clone <repo‑url>
   cd plagiarism-checker
   ```

2. **Create a virtual environment** (requires Python >=3.12):

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1   # PowerShell
   # or
   .venv\Scripts\activate.bat   # cmd.exe
   ```

3. **Install dependencies**

   ```powershell
   python -m pip install -r requirements.txt
   ```

   The `requirements.txt` now includes the `python-multipart` package required for file‑upload endpoints.

4. **(Optional) Pre‑download the SentenceTransformer model**

   The first run will download a small embedding model (`all-MiniLM-L6-v2`). To avoid the download during execution, you can pre‑fetch it:

   ```powershell
   python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', cache_folder='model_cache')"
   ```
   The code falls back to an offline‑only load and will gracefully continue if the model cannot be fetched.

---

## Environment Variables

Create a `.env` file in the project root (it is already present with sensible defaults). Below are the important variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `PC_DAILY_CHECKS_PER_USER` | Maximum number of plagiarism checks a user may run per day. | `5` |
| `POSTGRES_URL` | Connection string for a PostgreSQL instance (optional). If unreachable, the app falls back to SQLite. | (empty) |
| `SQLITE_PATH` | Path to the SQLite database (absolute path is enforced by the code). | `plagiarism_dev.db` |
| `REDIS_URL` | URL of a Redis server for RQ workers (optional). | (empty) |
| `HOST` | Host interface for the API server. | `0.0.0.0` |
| `PORT` | Port for the API server. | `8000` |

---

## Running the Application

### Run locally

- Start the backend:
  ```powershell
  uvicorn app.main:app --port 8000
  ```
- Open `http://127.0.0.1:8000` in Chrome or Edge, NOT the IDE's embedded preview and NOT Live Server (the embedded preview breaks file uploads with "DataCloneError: FormData could not be cloned").

### General Server Start

```powershell
uvicorn app.main:app --host $Env:HOST --port $Env:PORT
```

The server will start and expose the following key endpoints (among others):

- `GET /health` – health check (uses DB fallback information).
- `POST /api/check/upload` – multipart file upload for a plagiarism scan.
- `GET /api/jobs/{job_id}` – poll the status of an async job.
- `GET /api/user/jobs` – list recent jobs for the authenticated user.
- `GET /verify/{token}` – view a verification certificate.

Authentication is currently a simple header‑based mock (`X-User-Id`). Adjust as needed for your environment.

---

## Running Tests

The project uses **pytest**. To execute the full test suite:

```powershell
.\.venv\Scripts\pytest -q
```

All tests should now pass. The `pytest` command automatically ignores the optional load‑test script (`tests/load_test.py`).

---

## Running the Benchmark

A lightweight benchmark script (`benchmark.py`) is provided. It measures average latency for a typical upload‑scan‑retrieve flow.

```powershell
python benchmark.py
```

The script prints a summary table with request latency, DB write time, and model inference time.

---

## Project Structure Overview

```
plagiarism-checker/
├─ app/                 # FastAPI application, routers, dependencies
│   ├─ main.py          # Entry point, routes, DB init
│   ├─ rate_limit.py    # Rate‑limit utilities
│   └─ database.py      # SQLAlchemy engine & session handling
├─ pipeline/            # Core document processing pipeline
│   ├─ retrieve.py
│   └─ semantic.py
├─ worker/              # Background job dispatcher & store (DB‑backed)
│   ├─ dispatcher.py
│   └─ store.py
├─ tests/               # pytest test suite
├─ requirements.txt
├─ pyproject.toml       # pytest configuration
└─ README.md            # ← you are reading this
```

---

## Detection Capabilities & Algorithm Matrix

The platform implements an advanced multi-stage plagiarism detection pipeline:

| Capability | Module | Technique |
|---|---|---|
| **Exact Word-for-Word** | `pipeline/lexical.py` | 5-gram shingling with contiguous run grouping ($\ge 8$ words) |
| **Near-Exact Copying** | `pipeline/lexical.py` | Small gap bridging ($\le 3$ words) between adjacent matching runs |
| **Paraphrased Content** | `pipeline/semantic.py` | Dense embeddings (`all-MiniLM-L6-v2`) with Dual-Signal Rule (Cosine $\ge 0.85$ + Jaccard $\ge 0.20$) |
| **Open Web Search** | `pipeline/retrieve.py` | DuckDuckGo search query generation with disk cache and polite delays |
| **Academic Corpus** | `index/corpus.py` | Inverted index search with top-k candidate retrieval over indexed literature |
| **Self-Plagiarism** | `worker/tasks.py` | Dynamic DB query of author's earlier papers under the same account with `kind="self"` tagging |
| **Common Boilerplate** | `pipeline/exclude.py` | 30+ high-frequency academic boilerplate idioms filtered out to prevent false positives |
| **Bibliography & References** | `pipeline/exclude.py` | Multi-format section header detection in the latter 60% of the document |
| **Quoted & Cited Content** | `pipeline/exclude.py` | Quoted passages verified against APA, Harvard, and numeric brackets; uncited quotes flagged |
| **Small Matches Filtering** | `pipeline/score.py` | Low-overlap isolated fragments below threshold filtered or marked low-confidence |
| **Long Match Tracking** | `pipeline/score.py` | Tracks longest contiguous match from each source with confidence scoring |
| **Source Contribution %** | `pipeline/score.py` | Per-source percentage and word breakdown sorted in descending order |
| **Overall Similarity %** | `pipeline/score.py` | Overall percentage computed strictly over non-excluded scorable words |
| **Match Classification** | `pipeline/score.py` | Unified token ownership ensuring clear Exact / Near / Paraphrase labels |
| **Anti-Evasion** | `pipeline/evasion.py` | NFKC normalization, Cyrillic/Greek homoglyph replacement, zero-width removal, spaced letters |
| **Language Detection** | `pipeline/language.py` | Statistical stopword profiling (EN, ES, FR, DE) with confidence and compatibility flags |
| **Header/Footer Stripping** | `pipeline/extract.py` | Regex header/footer noise and page number removal |
| **Title Page & Acknowledgements** | `pipeline/exclude.py` | Exclusion of dissertation cover page preambles and acknowledgements sections |
| **OCR Support for Scanned PDFs** | `pipeline/extract.py` | Scanned document detection with PyMuPDF OCR fallback |
| **Overlapping Match Defense** | `pipeline/score.py` | Strict single-owner token mapping preventing double-counting |
| **AI Writing Indication** | `pipeline/ai_detect.py` | Sentence burstiness variance and AI cliche density analysis |

---

## Known Limitations & Untested Areas (Phase Summary)

**What has been done**
- Implemented all 22 items in the Detection Checklist.
- Added Title Page preamble & Acknowledgements section exclusion.
- Added Academic Boilerplate idiom filtering.
- Implemented Document Language Detection (`pipeline/language.py`).
- Implemented AI Writing Characteristics Indicator (`pipeline/ai_detect.py`).
- Added Self-Plagiarism detection against previous submissions by the author.
- Added Scanned PDF detection & OCR fallback in `pipeline/extract.py`.
- Instant sub-second PostgreSQL pre-check with SQLite fallback.
- Added frontend "My Scans" history modal, certificate copy button, and live quota tracking.
- Full test suite passing (all 78 unit & integration tests).

**What remains untested**
- **Redis / RQ integration** – the optional Redis queue path is not covered by tests; manual verification required if you enable it.
- **Large‑scale concurrency** – stress‑testing of rate‑limit under high parallel load is not automated.
- **Certificate HTML rendering** – visual correctness of the `/verify/{token}` page is not validated by tests.

**Known limitations**
- Model download fallback relies on internet connectivity check; in a fully offline environment the embedding step returns empty vectors, which may affect downstream similarity scores.
- SQLite is used as fallback; for production you should provision a robust Postgres instance and set `PC_DATABASE_URL`.
- The benchmark script is simplistic and does not simulate concurrent users.

---

## Future Improvements (optional)
- Add proper JWT‑based authentication.
- Implement pagination & filtering on job‑history endpoint.
- Provide a Dockerfile for containerised deployment.
- Integrate CI pipeline step to pre‑download the embedding model.
- Expand the benchmark to include concurrent load testing (e.g., with `locust`).

---

*End of README*
