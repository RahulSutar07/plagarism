"""Tests for privacy retention purge worker and legal disclosure endpoints."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.models import Base, Job, ScanResult
from worker.retention import (
    purge_expired_raw_texts,
    purge_expired_scan_records,
    run_retention_sweep,
)

client = TestClient(app)


def test_retention_purge_expired_raw_texts():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionTest = sessionmaker(bind=engine)

    with SessionTest() as db:
        now = datetime.now(timezone.utc)

        # 1. Old job (75 minutes old)
        job_old = Job(id="job-old-1", created_at=now - timedelta(minutes=75))
        db.add(job_old)
        result_old = ScanResult(
            job_id="job-old-1",
            title="Old Thesis",
            overall_similarity_pct=10.0,
            exact_pct=5.0,
            near_pct=3.0,
            paraphrase_pct=2.0,
            total_words=500,
            scored_words=450,
            raw_text="Confidential unpublished thesis draft.",
            created_at=now - timedelta(minutes=75),
        )
        db.add(result_old)

        # 2. Recent job (15 minutes old)
        job_recent = Job(id="job-recent-1", created_at=now - timedelta(minutes=15))
        db.add(job_recent)
        result_recent = ScanResult(
            job_id="job-recent-1",
            title="Recent Essay",
            overall_similarity_pct=5.0,
            exact_pct=2.0,
            near_pct=2.0,
            paraphrase_pct=1.0,
            total_words=300,
            scored_words=290,
            raw_text="Active scan text still within 1-hour window.",
            created_at=now - timedelta(minutes=15),
        )
        db.add(result_recent)
        db.commit()

        # Run text purge (60m default)
        purged_count = purge_expired_raw_texts(db, max_age_minutes=60)
        assert purged_count == 1

        # Verify old text is nulled
        db.expire_all()
        q_old = db.scalar(select(ScanResult).where(ScanResult.job_id == "job-old-1"))
        assert q_old.raw_text is None
        # Scores and title remain intact
        assert q_old.overall_similarity_pct == 10.0
        assert q_old.title == "Old Thesis"

        # Verify recent text is preserved
        q_recent = db.scalar(select(ScanResult).where(ScanResult.job_id == "job-recent-1"))
        assert q_recent.raw_text == "Active scan text still within 1-hour window."


def test_retention_purge_expired_jobs():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionTest = sessionmaker(bind=engine)

    with SessionTest() as db:
        now = datetime.now(timezone.utc)

        # 1. Job older than 30 days
        job_expired = Job(id="job-expired-31d", created_at=now - timedelta(days=32))
        db.add(job_expired)

        # 2. Job 5 days old
        job_active = Job(id="job-active-5d", created_at=now - timedelta(days=5))
        db.add(job_active)
        db.commit()

        deleted = purge_expired_scan_records(db, max_age_days=30)
        assert deleted == 1

        db.expire_all()
        assert db.scalar(select(Job).where(Job.id == "job-expired-31d")) is None
        assert db.scalar(select(Job).where(Job.id == "job-active-5d")) is not None


def test_run_retention_sweep():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionTest = sessionmaker(bind=engine)

    with SessionTest() as db:
        stats = run_retention_sweep(db)
        assert "nulled_raw_texts" in stats
        assert "purged_expired_jobs" in stats


def test_legal_endpoints_display_correct_policies():
    privacy_res = client.get("/legal/privacy")
    assert privacy_res.status_code == 200
    assert "Privacy Policy &amp; Data Minimization" in privacy_res.text or "Privacy Policy" in privacy_res.text
    assert "1-Hour Document Text Purge" in privacy_res.text
    assert "In-Memory Processing" in privacy_res.text

    terms_res = client.get("/legal/terms")
    assert terms_res.status_code == 200
    assert "Terms of Service" in terms_res.text
    assert "Educational Pre-Check Purpose" in terms_res.text
    assert "Not an Institutional Clearance Tool" in terms_res.text
