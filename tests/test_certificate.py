"""Unit and integration tests for Plagiarism Check Certificate generation and verification."""
import re
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import ScanResultSummary, SourceSummarySchema
from reports.certificate import (
    compute_integrity_hash,
    create_or_get_certificate,
    generate_certificate_id,
    generate_certificate_pdf,
)
from worker.store import get_job_store

client = TestClient(app)


def make_dummy_summary(title: str = "Test Academic Paper", is_partial: bool = False) -> ScanResultSummary:
    return ScanResultSummary(
        title=title,
        overall_similarity_pct=14.2,
        exact_pct=8.1,
        near_pct=4.1,
        paraphrase_pct=2.0,
        total_words=850,
        scored_words=800,
        matched_words=115,
        largest_single_source="arXiv:2201.05412 (9.5%)",
        is_partial=is_partial,
        partial_reason="Candidate query limit hit" if is_partial else "",
        searched_description="Local corpus (1,500 docs)",
        flags=["Cyrillic homoglyph normalization (2 characters converted)"],
        source_summaries=[
            SourceSummarySchema(
                source_id=1,
                label="https://arxiv.org/abs/2201.05412",
                kind="web",
                matched_words=80,
                percentage=9.5,
                confidence="high",
                longest_contiguous_run=14,
            )
        ],
        match_spans=[],
    )


def test_certificate_id_format():
    cert_id = generate_certificate_id()
    assert re.match(r"^PC-\d{4}-[2-9A-HJ-NP-Z]{6}$", cert_id)

    custom_id = generate_certificate_id(year=2030)
    assert custom_id.startswith("PC-2030-")


def test_compute_integrity_hash():
    h1 = compute_integrity_hash("Title", 1000, 950, 15.5, "2026-10-26 12:00 UTC")
    h2 = compute_integrity_hash("Title", 1000, 950, 15.5, "2026-10-26 12:00 UTC")
    h3 = compute_integrity_hash("Title", 1000, 950, 16.0, "2026-10-26 12:00 UTC")

    assert len(h1) == 64
    assert h1 == h2
    assert h1 != h3


def test_create_or_get_certificate():
    store = get_job_store()
    job_id = store.create_job()
    summary = make_dummy_summary()
    store.update_job(job_id, status="completed", progress_pct=100, result=summary)

    cert1 = create_or_get_certificate(job_id, summary)
    assert cert1.certificate_id.startswith("PC-")
    assert cert1.job_id == job_id
    assert len(cert1.token) >= 16
    assert len(cert1.doc_hash) == 64

    # Idempotent retrieval
    cert2 = create_or_get_certificate(job_id, summary)
    assert cert1.certificate_id == cert2.certificate_id
    assert cert1.token == cert2.token


def test_generate_certificate_pdf_bytes():
    store = get_job_store()
    job_id = store.create_job()
    summary = make_dummy_summary(is_partial=True)
    store.update_job(job_id, status="completed", progress_pct=100, result=summary)

    cert = create_or_get_certificate(job_id, summary)
    pdf_bytes = generate_certificate_pdf(cert)

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF-")


def test_generate_certificate_pdf_to_file(tmp_path: Path):
    store = get_job_store()
    job_id = store.create_job()
    summary = make_dummy_summary()
    cert = create_or_get_certificate(job_id, summary)

    target_file = tmp_path / "cert_output.pdf"
    generate_certificate_pdf(cert, output=target_file)

    assert target_file.exists()
    assert target_file.stat().st_size > 1000
    assert target_file.read_bytes().startswith(b"%PDF-")


def test_api_download_certificate_pdf_lifecycle():
    store = get_job_store()
    job_id = store.create_job()
    summary = make_dummy_summary(title="Deep Neural Networks Research")
    store.update_job(job_id, status="completed", progress_pct=100, result=summary)

    res = client.get(f"/api/jobs/{job_id}/certificate.pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF-")
    assert "attachment; filename=plagiarism_certificate_PC-" in res.headers["content-disposition"]


def test_api_download_certificate_not_found():
    res = client.get("/api/jobs/job-unknown-999/certificate.pdf")
    assert res.status_code == 404


def test_api_verify_endpoint_success_and_failure():
    store = get_job_store()
    job_id = store.create_job()
    summary = make_dummy_summary(title="Cryptography and Privacy")
    store.update_job(job_id, status="completed", progress_pct=100, result=summary)

    cert = create_or_get_certificate(job_id, summary)

    # Valid token lookup
    verify_res = client.get(f"/api/verify/{cert.token}")
    assert verify_res.status_code == 200
    body = verify_res.json()
    assert body["verified"] is True
    assert body["certificate_id"] == cert.certificate_id
    assert body["doc_hash"] == cert.doc_hash
    assert body["overall_similarity_pct"] == cert.overall_similarity_pct
    assert "does not store document text" in body["notice"]

    # Invalid token lookup
    invalid_res = client.get("/api/verify/token-does-not-exist-xyz")
    assert invalid_res.status_code == 404


def test_html_verification_page_privacy_and_display():
    store = get_job_store()
    job_id = store.create_job()
    summary = make_dummy_summary(title="Economic Cycles and Inflation")
    store.update_job(job_id, status="completed", progress_pct=100, result=summary)

    cert = create_or_get_certificate(job_id, summary)

    # Valid verification page
    page_res = client.get(f"/verify/{cert.token}")
    assert page_res.status_code == 200
    html = page_res.text
    assert "Verified Authentic Pre-Check Certificate" in html
    assert cert.certificate_id in html
    assert cert.doc_hash in html
    assert "does not store document text" in html

    # Strict Privacy Rule: Never display author or raw document body text
    assert "Author:" not in html

    # Invalid token verification page returns 404 HTML
    bad_page_res = client.get("/verify/bad-token-12345")
    assert bad_page_res.status_code == 404
    assert "Certificate Not Found or Expired" in bad_page_res.text
