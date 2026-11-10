# Plagiarism Pre-Check - REST API Reference

The Plagiarism Pre-Check REST API enables programmatic submission of documents for asynchronous similarity analysis, job polling, report generation, and public certificate verification.

All API responses use standard JSON formatting. Error responses return an RFC 7807 compliant structure containing a `detail` message.

---

## 1. Authentication

Most check endpoints are accessible anonymously with IP-based rate limiting (5 scans / 24 hours). Authenticated users enjoy tier-based quotas and scan history tracking.

Authentication uses standard Bearer JWT tokens in the `Authorization` header:
```http
Authorization: Bearer <access_token>
```

---

## 2. API Endpoints

### 2.1 Submit File for Analysis

Submit a PDF, DOCX, or plain text document for asynchronous plagiarism analysis.

- **Method**: `POST`
- **Path**: `/api/check/upload`
- **Content-Type**: `multipart/form-data`
- **Status Code**: `202 Accepted`

#### Form Parameters
| Parameter | Type | Required | Description |
|---|---|---|---|
| `file` | File Binary | Yes | Target document (`.pdf`, `.docx`, `.txt`). Max 25 MB. |
| `enable_web_search` | Boolean | No | Search open-web candidate sources (Default: `false`). |
| `enable_paraphrase` | Boolean | No | Enable neural bi-encoder paraphrase detection (Default: `true`). |

#### Response (`202 Accepted`)
```json
{
  "job_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "queued",
  "queue_position": 1,
  "estimated_wait_seconds": 5,
  "message": "Document accepted for plagiarism analysis."
}
```

#### Example cURL
```bash
curl -X POST "http://localhost:8000/api/check/upload" \
  -F "file=@academic_paper.pdf" \
  -F "enable_paraphrase=true"
```

---

### 2.2 Submit Pasted Text for Analysis

Submit raw text directly via JSON payload.

- **Method**: `POST`
- **Path**: `/api/check/paste`
- **Content-Type**: `application/json`
- **Status Code**: `202 Accepted`

#### Request Body
```json
{
  "text": "Academic writing requires original synthesis of research ideas...",
  "title": "Literature Review Section 3",
  "enable_web_search": false,
  "enable_paraphrase": true
}
```

#### Constraints
- `text`: Minimum 50 characters, minimum 50 words, maximum 5,000 words.
- `title`: Maximum 150 characters.

---

### 2.3 Poll Job Status & Results

Check the current processing status, progress percentage, and analysis results for a job.

- **Method**: `GET`
- **Path**: `/api/jobs/{job_id}`
- **Status Code**: `200 OK`

#### Response When Processing
```json
{
  "job_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "processing",
  "stage": "matching",
  "progress_pct": 65,
  "error": null,
  "result": null,
  "created_at": 1729934100.0,
  "updated_at": 1729934105.0
}
```

#### Response When Completed
```json
{
  "job_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "completed",
  "stage": "completed",
  "progress_pct": 100,
  "error": null,
  "result": {
    "title": "academic_paper.pdf",
    "overall_similarity_pct": 14.5,
    "exact_pct": 8.0,
    "near_pct": 4.0,
    "paraphrase_pct": 2.5,
    "total_words": 1500,
    "scored_words": 1380,
    "matched_words": 200,
    "largest_single_source": "Wikipedia: Machine Learning",
    "is_partial": false,
    "partial_reason": "",
    "searched_description": "Local Academic Corpus & Open Web",
    "flags": [],
    "source_summaries": [
      {
        "source_id": 1,
        "label": "Wikipedia: Machine Learning",
        "kind": "web",
        "matched_words": 120,
        "percentage": 8.7,
        "confidence": "high",
        "longest_contiguous_run": 24
      }
    ],
    "match_spans": [
      {
        "start_token_idx": 45,
        "end_token_idx": 69,
        "start_char": 280,
        "end_char": 435,
        "source_id": 1,
        "match_type": "exact",
        "matched_word_count": 24
      }
    ]
  },
  "created_at": 1729934100.0,
  "updated_at": 1729934112.0
}
```

---

### 2.4 Download PDF Similarity Report

Download an official, presentation-ready PDF report detailing full similarity breakdown, source attribution, and matched passage spans.

- **Method**: `GET`
- **Path**: `/api/jobs/{job_id}/report.pdf`
- **Status Code**: `200 OK`
- **Response**: `application/pdf` (Attachment)

---

### 2.5 Download PDF Pre-Check Certificate

Download a single-page, tamper-resistant PDF Certificate featuring an academic border, cryptographic SHA-256 document hash, and an embedded verification QR code.

- **Method**: `GET`
- **Path**: `/api/jobs/{job_id}/certificate.pdf`
- **Status Code**: `200 OK`
- **Response**: `application/pdf` (Attachment)

---

### 2.6 Public Certificate Verification (Zero Raw Text Exposure)

Third parties (professors, editors, institutions) can verify certificates without ever exposing the author's document text.

#### JSON Verification Endpoint
- **Method**: `GET`
- **Path**: `/api/verify/{token}`
- **Response**:
```json
{
  "valid": true,
  "certificate_id": "PC-2026-AB12CD",
  "title": "academic_paper.pdf",
  "created_at": "2026-10-26 15:00 UTC",
  "overall_similarity_pct": 14.5,
  "exact_pct": 8.0,
  "near_pct": 4.0,
  "paraphrase_pct": 2.5,
  "total_words": 1500,
  "scored_words": 1380,
  "doc_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "primary_sources": ["Wikipedia: Machine Learning"],
  "is_partial": false,
  "partial_reason": "",
  "flags": []
}
```

#### Public HTML Verification Page
- **Method**: `GET`
- **Path**: `/verify/{token}`
- **Response**: `text/html` (Responsive, mobile-optimized Tailwind verification card)

---

### 2.7 User Authentication Endpoints

#### Register User
- **Method**: `POST`
- **Path**: `/api/auth/register`
- **Body**: `{"email": "scholar@university.edu", "password": "SecurePassword123!"}`
- **Response**: `201 Created` with JWT access token.

#### Login User
- **Method**: `POST`
- **Path**: `/api/auth/login`
- **Body**: `{"email": "scholar@university.edu", "password": "SecurePassword123!"}`
- **Response**: `200 OK` with JWT access token.

#### Get Current User Profile
- **Method**: `GET`
- **Path**: `/api/auth/me`
- **Headers**: `Authorization: Bearer <token>`
- **Response**:
```json
{
  "id": 1,
  "email": "scholar@university.edu",
  "role": "user",
  "tier": "free",
  "created_at": "2026-10-26 14:00 UTC",
  "daily_quota": 5,
  "daily_remaining": 4
}
```

---

### 2.8 System Diagnostics & Health

- **Method**: `GET`
- **Path**: `/health`
- **Response**:
```json
{
  "status": "healthy",
  "engine_version": "1.0.0",
  "database": "connected",
  "worker_disk_access": "read_write",
  "retention_status": "active",
  "timestamp": "2026-10-26T15:05:00Z"
}
```

---

## 3. Standard HTTP Status Codes

| Status Code | Description | Scenario |
|---|---|---|
| `200 OK` | Request succeeded | Status polling, downloads, profile retrieval |
| `201 Created` | Resource created | Successful user registration |
| `202 Accepted` | Async job queued | Check submission accepted for worker processing |
| `400 Bad Request` | Client validation error | Magic byte mismatch, under/over word limits |
| `401 Unauthorized`| Authentication error | Invalid credentials or expired JWT token |
| `404 Not Found` | Resource not found | Invalid `job_id` or certificate `token` |
| `429 Too Many Requests` | Rate limit breached | Exceeded 5 daily scans or active scan in progress |
| `503 Service Unavailable` | Backpressure drop | Queue saturated (100 jobs) or DB degraded |
