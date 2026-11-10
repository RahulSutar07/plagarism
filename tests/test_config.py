from app.config import Settings


def test_spec_limits_are_defaults():
    s = Settings()
    assert s.max_file_mb == 7
    assert s.max_file_bytes == 7 * 1024 * 1024
    assert (s.min_words, s.max_words) == (100, 30_000)
    assert s.max_pdf_pages == 200
    assert s.max_ocr_pages == 40
    assert s.max_docx_uncompressed_mb == 50
    assert s.job_timeout_s == 180
    assert s.queue_cap == 20
    assert s.concurrent_jobs_per_user == 1
    assert s.daily_checks_per_user == 5
    assert s.report_retention_days == 30
    assert set(s.allowed_extensions) == {"pdf", "docx", "txt"}


def test_env_override(monkeypatch):
    monkeypatch.setenv("PC_DAILY_CHECKS_PER_USER", "9")
    assert Settings().daily_checks_per_user == 9
