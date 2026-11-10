"""Security audit suite testing OWASP Top 10 vulnerabilities and platform defenses.

Verifies:
1. Zip-bomb expansion defense.
2. Magic-byte file spoofing resistance.
3. Cross-Site Scripting (XSS) neutralization in HTML outputs.
4. SQL injection immunity.
5. Zero raw document text disclosure in error traces.
6. Queue capacity denial-of-service backpressure.
"""
import io
import zipfile
import pytest
from fastapi.testclient import TestClient

from app.main import app
from pipeline.extract import ExtractionError, extract_document
from worker.dispatcher import QueueFullError, enqueue_plagiarism_job
from worker.store import get_job_store

client = TestClient(app)


def test_zip_bomb_defense():
    """Verify DOCX uncompressed size limit rejects decompression bombs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 10MB of zeroes compresses to a few bytes
        zf.writestr("word/document.xml", b"0" * (10 * 1024 * 1024))

    bomb_bytes = buf.getvalue()

    # Testing with a low threshold (e.g. 5MB) to verify zip-bomb detection logic
    with pytest.raises(ExtractionError) as exc_info:
        extract_document(bomb_bytes, filename="paper.docx", max_docx_uncompressed_bytes=5 * 1024 * 1024)

    assert "exceeds safety limit" in str(exc_info.value)


def test_magic_byte_spoofing_resistance():
    """Reject executable or HTML binaries masquerading as PDF or DOCX."""
    # 1. Renamed Windows executable (MZ header)
    fake_pdf = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00" + b"A" * 500
    res1 = client.post(
        "/api/check/upload",
        files={"file": ("academic_paper.pdf", io.BytesIO(fake_pdf), "application/pdf")},
    )
    assert res1.status_code == 400
    assert "magic bytes mismatch" in res1.json()["detail"]

    # 2. Renamed HTML script file
    fake_docx = b"<!DOCTYPE html><html><body><script>malicious();</script></body></html>"
    res2 = client.post(
        "/api/check/upload",
        files={"file": ("report.docx", io.BytesIO(fake_docx), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert res2.status_code == 400
    assert "magic bytes mismatch" in res2.json()["detail"]


def test_xss_neutralization_in_public_verification_page():
    """Malicious scripts in titles or metadata must be sanitized on public HTML pages."""
    store = get_job_store()
    job_id = store.create_job()
    xss_payload = "<script>alert('xss_attack');</script><img src=x onerror=alert(1)>"

    from app.schemas import ScanResultSummary
    summary = ScanResultSummary(
        title=xss_payload,
        overall_similarity_pct=5.0,
        exact_pct=2.0,
        near_pct=2.0,
        paraphrase_pct=1.0,
        total_words=200,
        scored_words=190,
        matched_words=10,
        largest_single_source="None",
        is_partial=False,
        partial_reason="",
        searched_description="Corpus",
        flags=[xss_payload],
        source_summaries=[],
        match_spans=[],
    )
    store.update_job(job_id, status="completed", progress_pct=100, result=summary)

    from reports.certificate import create_or_get_certificate
    cert = create_or_get_certificate(job_id, summary)

    # Fetch public verification HTML
    page_res = client.get(f"/verify/{cert.token}")
    assert page_res.status_code == 200
    html = page_res.text

    # Raw script tag must not execute unescaped
    assert "<script>alert('xss_attack');</script>" not in html
    assert "&lt;script&gt;" in html


def test_sql_injection_resistance():
    """Verify parameterized queries resist standard SQL injection vectors."""
    sqli_email = "admin' OR '1'='1' -- @domain.com"
    res = client.post(
        "/api/auth/login",
        json={"email": sqli_email, "password": "Password123!"},
    )
    # Rejects as invalid credentials, does not crash with SQL syntax error
    assert res.status_code == 401


def test_queue_capacity_defense():
    """Reject submissions with HTTP 503 when queue cap is reached."""
    store = get_job_store()
    # Temporarily saturate queue
    with store._lock:
        original_jobs = dict(store._jobs)
        for i in range(25):
            store._jobs[f"job-flood-{i}"] = type("DummyRecord", (), {
                "status": "queued",
                "created_at": float(i),
            })()

    try:
        sample_text = ("Distributed systems require fault tolerance mechanisms to ensure high availability. ") * 8
        with pytest.raises(QueueFullError):
            enqueue_plagiarism_job(raw_text=sample_text, title="Test")
    finally:
        # Restore store
        with store._lock:
            store._jobs = original_jobs


def test_zero_raw_text_leakage_in_error_responses():
    """Ensure error messages never regurgitate raw document contents."""
    sensitive_text = "SUPER_SECRET_PATENT_FORMULA_XYZ"
    res = client.post(
        "/api/check/paste",
        json={"text": f"This is an intentionally short paragraph containing confidential secret {sensitive_text} designed to test raw leakage."},
    )
    assert res.status_code == 400
    # Detail should report word count failure, never raw text snippet
    assert sensitive_text not in res.json()["detail"]
