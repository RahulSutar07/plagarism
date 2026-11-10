"""FastAPI entrypoint and asynchronous plagiarism check API endpoints."""
from __future__ import annotations

import html
from pathlib import Path
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    EMAIL_REGEX,
    TokenResponse,
    UserLoginRequest,
    UserProfileResponse,
    UserRegisterRequest,
    create_access_token,
    get_current_user,
    get_optional_user,
    hash_password,
    verify_password,
)
from app.config import get_settings
from app.database import get_db, init_db
from app.models import User
from app.rate_limit import (
    check_and_increment_rate_limit,
    enforce_concurrency_limit,
    get_client_identifier,
)
from app.schemas import (
    CertificateVerificationResponse,
    JobStatusResponse,
    JobSubmissionResponse,
    PasteSubmissionRequest,
)
from app.validation import (
    ValidationError,
    validate_file_magic_bytes,
    validate_upload_limits,
    validate_word_counts,
)
from app.wording import (
    CERTIFICATE_DISCLAIMER,
    COVERAGE_NOTE,
    INSTITUTION_NOTE,
    POSITIONING,
)
from pipeline.extract import ExtractionError, extract_document
from reports.certificate import create_or_get_certificate, generate_certificate_pdf
from reports.pdf_report import generate_pdf_report
from worker.dispatcher import QueueFullError, enqueue_plagiarism_job
from worker.store import get_job_store
from app.sentry import init_sentry

settings = get_settings()

# Initialize tables (creates SQLite or PostgreSQL tables if missing)
init_db()

# Initialize Sentry error reporting if configured
init_sentry()

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
INDEX_HTML = FRONTEND_DIR / "index.html"

app = FastAPI(
    title="Plagiarism Pre-Check API",
    version=settings.engine_version,
    description="High-Accuracy Asynchronous Plagiarism Pre-Check Platform",
)

# Enable CORS for local Next.js frontend, localhost:8000, and configured site_url
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=r"^https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def serve_frontend():
    """Serve web user interface."""
    if INDEX_HTML.exists():
        return FileResponse(INDEX_HTML)
    return {"message": "Plagiarism Pre-Check API running."}


@app.get("/health")
def health() -> dict:
    """System health check and diagnostic monitoring."""
    from datetime import datetime, timezone
    from sqlalchemy import text
    from app.database import SessionLocal

    # Test database connectivity
    db_status = "connected"
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unreachable: {e}"

    # Test cache/worker disk access
    disk_status = "ok"
    try:
        test_cache = Path(".pc_cache")
        test_cache.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        disk_status = f"error: {e}"

    is_healthy = db_status == "connected" and disk_status == "ok"

    return {
        "status": "ok" if is_healthy else "degraded",
        "env": settings.env,
        "engine_version": settings.engine_version,
        "thresholds_version": settings.thresholds_version,
        "database": db_status,
        "worker_disk": disk_status,
        "retention_policy": f"{settings.job_text_max_age_minutes}m text purge / {settings.report_retention_days}d report expiry",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }



@app.get("/limits")
def limits() -> dict:
    """Shown to users before upload (spec Section 4)."""
    return {
        "max_file_mb": settings.max_file_mb,
        "allowed_types": list(settings.allowed_extensions),
        "min_words": settings.min_words,
        "max_words": settings.max_words,
        "max_paste_words": settings.max_paste_words,
        "max_pdf_pages": settings.max_pdf_pages,
        "max_ocr_pages": settings.max_ocr_pages,
        "daily_checks_per_user": settings.daily_checks_per_user,
        "positioning": POSITIONING,
        "institution_note": INSTITUTION_NOTE,
        "coverage_note": COVERAGE_NOTE,
    }


# --- Authentication Endpoints ---

@app.post(
    "/api/auth/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_user(payload: UserRegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Register new user account."""
    if not EMAIL_REGEX.match(payload.email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email address format.")

    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="An account with this email already exists.")

    new_user = User(
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        role="user",
        tier="free",
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    token = create_access_token({"sub": str(new_user.id), "email": new_user.email, "tier": new_user.tier})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user_id=new_user.id,
        email=new_user.email,
        tier=new_user.tier,
    )


@app.post("/api/auth/login", response_model=TokenResponse)
def login_user(payload: UserLoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Authenticate existing user and issue JWT bearer token."""
    user = db.scalar(select(User).where(User.email == payload.email.lower(), User.is_active.is_(True)))
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token({"sub": str(user.id), "email": user.email, "tier": user.tier})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        email=user.email,
        tier=user.tier,
    )


@app.get("/api/auth/me", response_model=UserProfileResponse)
def get_user_profile(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    """Retrieve authenticated user details and remaining scan quota."""
    from datetime import datetime, timedelta, timezone
    from app.models import RateLimitRecord

    _, key = get_client_identifier(request, user=user)
    now = datetime.now(timezone.utc)
    record = db.scalars(
        select(RateLimitRecord)
        .where(RateLimitRecord.key_hash == key)
        .where(RateLimitRecord.window_start >= now - timedelta(hours=24))
        .order_by(RateLimitRecord.window_start.desc())
        .limit(1)
    ).first()
    used = record.scan_count if record else 0
    quota = 999999 if user.tier == "pro" else settings.daily_checks_per_user
    remaining = max(0, quota - used)

    return UserProfileResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        tier=user.tier,
        created_at=user.created_at.strftime("%Y-%m-%d %H:%M UTC"),
        daily_quota=quota,
        daily_remaining=remaining,
    )


@app.get("/api/user/jobs")
def get_user_jobs(
    limit: int = 20,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve recent plagiarism check history for the authenticated user with pagination."""
    from app.models import Job as DBJob
    safe_limit = min(max(1, limit), 100)
    safe_offset = max(0, offset)
    jobs = db.scalars(
        select(DBJob)
        .where(DBJob.user_id == user.id)
        .order_by(DBJob.created_at.desc())
        .offset(safe_offset)
        .limit(safe_limit)
    ).all()
    return [
        {
            "job_id": j.id,
            "status": j.status,
            "stage": j.stage,
            "progress_pct": j.progress_pct,
            "title": j.result.title if j.result else "Document",
            "overall_similarity_pct": j.result.overall_similarity_pct if j.result else None,
            "created_at": j.created_at.strftime("%Y-%m-%d %H:%M UTC") if j.created_at else "",
            "certificate_id": j.certificates[0].certificate_id if j.certificates else None,
            "token": j.certificates[0].token if j.certificates else None,
        }
        for j in jobs
    ]


# --- Scanning Endpoints with Rate Limiting & Concurrency Defense ---

@app.post(
    "/api/check/paste",
    response_model=JobSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@app.post(
    "/api/check/paste/",
    response_model=JobSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=False,
)
# Removed duplicate OPTIONS and GET routes; POST is sufficient
def check_pasted_text(
    request: Request,
    payload: PasteSubmissionRequest = None,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Submit pasted text for asynchronous plagiarism analysis with rate limit enforcement."""
    # POST only; OPTIONS and GET are handled by CORSMiddleware

    if payload is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing submission payload.")

    words = payload.text.split()
    try:
        validate_word_counts(len(words), is_paste=True)

        # Rate limiting and concurrency check
        _, key = get_client_identifier(request, user)
        enforce_concurrency_limit(key, user.id if user else None)
        check_and_increment_rate_limit(db, key, tier=user.tier if user else "free")

        job_id, queue_pos = enqueue_plagiarism_job(
            raw_text=payload.text,
            title=payload.title,
            enable_web_search=payload.enable_web_search,
            enable_paraphrase=payload.enable_paraphrase,
            queue_name=settings.fast_queue,
            identifier=key,
            user_id=user.id if user else None,
        )
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except QueueFullError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    return JobSubmissionResponse(
        job_id=job_id,
        status="queued",
        queue_position=queue_pos,
        estimated_wait_seconds=max(5, queue_pos * 10),
        message="Document successfully queued for analysis.",
    )


@app.post(
    "/api/check/upload",
    response_model=JobSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@app.post(
    "/api/check/upload/",
    response_model=JobSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=False,
)
# Removed duplicate OPTIONS and GET routes; POST is sufficient
async def check_uploaded_file(
    request: Request,
    file: UploadFile = File(default=None),
    title: str | None = Form(default=None),
    enable_web_search: bool = Form(default=False),
    enable_paraphrase: bool = Form(default=True),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Upload document (PDF, DOCX, TXT) for in-memory extraction and async check with rate limits."""
    # POST only; OPTIONS and GET are handled by CORSMiddleware

    if file is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file uploaded.")

    filename = file.filename or "uploaded_document"
    doc_title = title.strip() if title and title.strip() else filename

    # Read content in memory
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read upload stream: {e}",
        )

    # Server-side validation
    try:
        validate_upload_limits(content, is_paste=False)
        validate_file_magic_bytes(filename, content)
        extraction = extract_document(
            content,
            filename=filename,
            max_pages=settings.max_pdf_pages,
            max_docx_uncompressed_bytes=settings.max_docx_uncompressed_bytes,
        )
        validate_word_counts(extraction.word_count, is_paste=False)
    except (ValidationError, ExtractionError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Document parsing error: {e}",
        )

    # Discard binary content immediately
    del content

    # Rate limiting & concurrency check
    _, key = get_client_identifier(request, user)
    enforce_concurrency_limit(key, user.id if user else None)
    check_and_increment_rate_limit(db, key, tier=user.tier if user else "free")

    # Enqueue job
    try:
        job_id, queue_pos = enqueue_plagiarism_job(
            raw_text=extraction.text,
            title=doc_title,
            enable_web_search=enable_web_search,
            enable_paraphrase=enable_paraphrase,
            queue_name=settings.fast_queue,
            identifier=key,
            user_id=user.id if user else None,
        )
    except QueueFullError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    return JobSubmissionResponse(
        job_id=job_id,
        status="queued",
        queue_position=queue_pos,
        estimated_wait_seconds=max(5, queue_pos * 10),
        message="Document extracted in memory and queued for analysis.",
    )



@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str) -> JobStatusResponse:
    """Poll job status, progress percentage, queue position, or final scan results."""
    store = get_job_store()
    record = store.get_job(job_id)

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )

    queue_pos = store.get_queue_position(job_id) if record.status == "queued" else None

    cert_id = None
    token = None
    if record.status == "completed" and record.result:
        try:
            cert = create_or_get_certificate(job_id, record.result)
            cert_id = cert.certificate_id
            token = cert.token
        except Exception:
            pass

    return JobStatusResponse(
        job_id=record.job_id,
        status=record.status,
        stage=record.stage,
        progress_pct=record.progress_pct,
        queue_position=queue_pos,
        error=record.error,
        result=record.result,
        certificate_id=cert_id,
        verification_token=token,
    )


@app.get("/api/jobs/{job_id}/report.pdf")
def download_pdf_report(job_id: str):
    """Download official PDF plagiarism report for a completed scan."""
    store = get_job_store()
    record = store.get_job(job_id)

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )

    if record.status != "completed" or not record.result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job '{job_id}' is in status '{record.status}'. PDF report is only available after scan completion.",
        )

    pdf_bytes = generate_pdf_report(record.result)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=plagiarism_report_{job_id}.pdf"
        },
    )


@app.get("/api/jobs/{job_id}/certificate.pdf")
def download_certificate_pdf(job_id: str):
    """Download official verification PDF certificate for a completed scan."""
    store = get_job_store()
    record = store.get_job(job_id)

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )

    if record.status != "completed" or not record.result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job '{job_id}' is in status '{record.status}'. Certificate is only available after scan completion.",
        )

    cert = create_or_get_certificate(job_id, record.result)
    pdf_bytes = generate_certificate_pdf(cert)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=plagiarism_certificate_{cert.certificate_id}.pdf"
        },
    )


@app.get("/api/verify/{token}", response_model=CertificateVerificationResponse)
def verify_certificate_api(token: str) -> CertificateVerificationResponse:
    """Public JSON verification endpoint for authenticating certificate tokens."""
    store = get_job_store()
    cert = store.get_certificate_by_token(token)

    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certificate for verification token '{token}' was not found or has expired.",
        )

    return CertificateVerificationResponse(
        verified=True,
        certificate_id=cert.certificate_id,
        title=cert.title,
        created_at=cert.created_at,
        overall_similarity_pct=cert.overall_similarity_pct,
        exact_pct=cert.exact_pct,
        near_pct=cert.near_pct,
        paraphrase_pct=cert.paraphrase_pct,
        total_words=cert.total_words,
        scored_words=cert.scored_words,
        doc_hash=cert.doc_hash,
        primary_sources=cert.primary_sources,
        is_partial=cert.is_partial,
        partial_reason=cert.partial_reason,
        flags=cert.flags,
    )


def _render_verification_html(cert, token: str) -> str:
    """Render public HTML verification page adhering to zero raw text exposure rules."""
    safe_token = html.escape(token)
    if not cert:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Certificate Not Found - Plagiarism Pre-Check</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50 min-h-screen flex items-center justify-center p-4">
  <div class="max-w-md w-full bg-white rounded-2xl shadow-sm border border-slate-200 p-8 text-center">
    <div class="w-16 h-16 bg-red-100 text-red-600 rounded-full flex items-center justify-center mx-auto mb-4 text-2xl font-bold">
      ✕
    </div>
    <h1 class="text-xl font-bold text-slate-900 mb-2">Certificate Not Found or Expired</h1>
    <p class="text-sm text-slate-500 mb-6">No active verification record was found matching token <code class="bg-slate-100 px-1 py-0.5 rounded text-xs">{safe_token}</code>. The record may have expired or the verification link is invalid.</p>
    <a href="/" class="inline-block bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2.5 px-6 rounded-lg text-sm transition">Return to Home</a>
  </div>
</body>
</html>"""

    safe_title = html.escape(cert.title or "Untitled Document")
    safe_cert_id = html.escape(str(cert.certificate_id))
    flags_html = "".join(f"<li class='text-xs text-slate-600'>&bull; {html.escape(str(f))}</li>" for f in cert.flags) if cert.flags else "<li class='text-xs text-emerald-700 font-medium'>&bull; Clean (no formatting evasion detected)</li>"
    sources_html = "".join(f"<li class='text-xs text-slate-600'>&bull; {html.escape(str(s))}</li>" for s in cert.primary_sources) if cert.primary_sources else "<li class='text-xs text-slate-500'>&bull; No significant reference sources above threshold.</li>"
    sim_color = "text-red-600" if cert.overall_similarity_pct > 25 else "text-amber-600" if cert.overall_similarity_pct > 15 else "text-emerald-600"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Verified Certificate {safe_cert_id} - Plagiarism Pre-Check</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    body {{ font-family: 'Inter', sans-serif; }}
    .mono {{ font-family: 'JetBrains Mono', monospace; }}
  </style>
</head>
<body class="bg-slate-50 text-slate-900 min-h-screen py-10 px-4">
  <div class="max-w-2xl mx-auto bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
    <!-- Header -->
    <div class="bg-gradient-to-r from-blue-900 to-indigo-900 text-white p-6 sm:p-8">
      <div class="flex items-center justify-between mb-4">
        <span class="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
          ● Verified Authentic Pre-Check Certificate
        </span>
        <span class="text-xs text-slate-300 font-mono">{cert.created_at}</span>
      </div>
      <h1 class="text-2xl font-bold tracking-tight mb-1">{safe_cert_id}</h1>
      <p class="text-sm text-slate-300">Document Title: <span class="font-semibold text-white">{safe_title}</span></p>
    </div>

    <div class="p-6 sm:p-8 space-y-6">
      <!-- Score Overview -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div class="p-3.5 bg-slate-50 rounded-xl border border-slate-200 text-center">
          <div class="text-2xl font-extrabold {sim_color}">{cert.overall_similarity_pct:.1f}%</div>
          <div class="text-[11px] font-bold text-slate-600 uppercase mt-0.5">Overall Similarity</div>
        </div>
        <div class="p-3.5 bg-slate-50 rounded-xl border border-slate-200 text-center">
          <div class="text-xl font-bold text-red-600">{cert.exact_pct:.1f}%</div>
          <div class="text-[11px] font-medium text-slate-500 mt-0.5">Exact Match</div>
        </div>
        <div class="p-3.5 bg-slate-50 rounded-xl border border-slate-200 text-center">
          <div class="text-xl font-bold text-amber-600">{cert.near_pct:.1f}%</div>
          <div class="text-[11px] font-medium text-slate-500 mt-0.5">Near Match</div>
        </div>
        <div class="p-3.5 bg-slate-50 rounded-xl border border-slate-200 text-center">
          <div class="text-xl font-bold text-indigo-600">{cert.paraphrase_pct:.1f}%</div>
          <div class="text-[11px] font-medium text-slate-500 mt-0.5">Paraphrased</div>
        </div>
      </div>

      <!-- Scope & Words -->
      <div class="bg-slate-50 p-4 rounded-xl border border-slate-200 text-xs text-slate-700 flex justify-between items-center">
        <span><b>Total Words:</b> {cert.total_words}</span>
        <span><b>Scored Words:</b> {cert.scored_words} ({cert.total_words - cert.scored_words} excluded)</span>
        <span><b>Status:</b> {"Partial Scan" if cert.is_partial else "Complete Scan"}</span>
      </div>

      <!-- Primary Sources -->
      <div>
        <h2 class="text-xs font-bold text-slate-900 uppercase tracking-wider mb-2">Primary Reference Matches</h2>
        <ul class="space-y-1">{sources_html}</ul>
      </div>

      <!-- Evasion Flags -->
      <div>
        <h2 class="text-xs font-bold text-slate-900 uppercase tracking-wider mb-2">Audit & Integrity Inspection</h2>
        <ul class="space-y-1">{flags_html}</ul>
      </div>

      <!-- Cryptographic Hash -->
      <div class="p-4 bg-slate-900 text-slate-200 rounded-xl space-y-1.5">
        <div class="text-[11px] font-bold uppercase tracking-wider text-slate-400">Cryptographic Document Integrity Digest (SHA-256)</div>
        <div class="mono text-xs break-all text-emerald-400 selection:bg-emerald-800">{cert.doc_hash}</div>
        <p class="text-[11px] text-slate-400 mt-1">Plagiarism Pre-Check does not store document text. The document hash allows the author to prove this certificate corresponds to their file.</p>
      </div>

      <!-- Action -->
      <div class="pt-2 flex justify-between items-center border-t border-slate-200">
        <a href="/api/jobs/{cert.job_id}/certificate.pdf" class="inline-flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-lg text-xs shadow transition">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
          <span>Download Official PDF Certificate</span>
        </a>
        <a href="/" class="text-xs font-medium text-slate-600 hover:text-blue-600">Run a New Pre-Check</a>
      </div>

      <!-- Mandatory Disclaimers -->
      <div class="pt-4 border-t border-slate-100 text-[10px] text-slate-400 leading-relaxed space-y-1">
        <p><b>Notice:</b> This certificate confirms that the document was analyzed by Plagiarism Pre-Check on the date indicated. It is not an institutional clearance certificate and does not guarantee that institutional checks (such as Turnitin or iThenticate) will produce identical results.</p>
        <p><b>Disclaimer:</b> {CERTIFICATE_DISCLAIMER} {INSTITUTION_NOTE}</p>
      </div>
    </div>
  </div>
</body>
</html>"""


@app.get("/verify/{token}", response_class=HTMLResponse, include_in_schema=False)
def verify_certificate_html(token: str) -> HTMLResponse:
    """Public verification webpage confirming certificate authenticity and metadata."""
    store = get_job_store()
    cert = store.get_certificate_by_token(token)
    html_content = _render_verification_html(cert, token)
    status_code = status.HTTP_200_OK if cert else status.HTTP_404_NOT_FOUND
    return HTMLResponse(content=html_content, status_code=status_code)


@app.get("/legal/privacy", response_class=HTMLResponse, include_in_schema=False)
def legal_privacy() -> HTMLResponse:
    """Privacy policy explaining data minimization and 1-hour retention purge."""
    content = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Privacy Policy - Plagiarism Pre-Check</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50 text-slate-800 p-8 max-w-3xl mx-auto font-sans leading-relaxed">
  <div class="bg-white p-8 rounded-xl border border-slate-200 space-y-4">
    <h1 class="text-2xl font-bold text-slate-900">Privacy Policy & Data Minimization</h1>
    <p class="text-sm text-slate-500">Effective Date: October 2026</p>
    <hr class="border-slate-200">
    <h2 class="text-base font-semibold text-slate-800">1. In-Memory Processing & Discard Policy</h2>
    <p class="text-sm">Uploaded binary files (.pdf, .docx, .txt) are parsed in memory and immediately discarded. File binaries are never written to server disks or cloud storage.</p>
    <h2 class="text-base font-semibold text-slate-800">2. 1-Hour Document Text Purge</h2>
    <p class="text-sm">Raw document text is held temporarily in a secured queue to compute similarity matches. Exactly one hour after scan completion, raw document text is purged permanently (nulled) from our systems.</p>
    <h2 class="text-base font-semibold text-slate-800">3. No Selling or Adding to Institutional Databases</h2>
    <p class="text-sm">We never share, sell, or index your original unpublished papers into commercial databases or public repositories. Your document will never be flagged against itself in institutional systems (e.g. Turnitin/iThenticate) as a result of using this pre-check.</p>
    <h2 class="text-base font-semibold text-slate-800">4. IP Anonymization</h2>
    <p class="text-sm">IP addresses used for fair rate limiting are cryptographically salted and hashed. We never store plain client IP addresses in server logs.</p>
    <div class="pt-4 border-t border-slate-100">
      <a href="/" class="text-sm font-medium text-blue-600 hover:underline">&larr; Return to Application</a>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=content)


@app.get("/legal/terms", response_class=HTMLResponse, include_in_schema=False)
def legal_terms() -> HTMLResponse:
    """Terms of service and educational pre-check disclaimers."""
    content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Terms of Service - Plagiarism Pre-Check</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50 text-slate-800 p-8 max-w-3xl mx-auto font-sans leading-relaxed">
  <div class="bg-white p-8 rounded-xl border border-slate-200 space-y-4">
    <h1 class="text-2xl font-bold text-slate-900">Terms of Service & Academic Use</h1>
    <p class="text-sm text-slate-500">Effective Date: October 2026</p>
    <hr class="border-slate-200">
    <h2 class="text-base font-semibold text-slate-800">1. Educational Pre-Check Purpose</h2>
    <p class="text-sm">{POSITIONING}</p>
    <h2 class="text-base font-semibold text-slate-800">2. Not an Institutional Clearance Tool</h2>
    <p class="text-sm">{INSTITUTION_NOTE} Similarity scores are indicators, not proof of misconduct. Final academic determination requires qualified human review under your institution's specific regulations.</p>
    <h2 class="text-base font-semibold text-slate-800">3. Fair Use & Submission Limits</h2>
    <p class="text-sm">Users agree not to submit unlawful material or engage in automated scraping. Free accounts are limited to {settings.daily_checks_per_user} scans per day and 1 active concurrent job.</p>
    <div class="pt-4 border-t border-slate-100">
      <a href="/" class="text-sm font-medium text-blue-600 hover:underline">&larr; Return to Application</a>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=content)


