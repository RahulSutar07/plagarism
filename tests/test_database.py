"""Tests for SQLAlchemy database models and operations."""
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Base, Certificate, Job, RateLimitRecord, ScanResult, User


def test_database_models_crud():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionTest = sessionmaker(bind=engine)

    with SessionTest() as db:
        # Create user
        user = User(
            email="researcher@university.edu",
            hashed_password="hashed_pw_xyz",
            role="user",
            tier="free",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        assert user.id is not None
        assert user.is_active is True

        # Create job
        job = Job(
            id="job-test-db-001",
            user_id=user.id,
            status="completed",
            stage="completed",
            progress_pct=100,
        )
        db.add(job)
        db.commit()

        # Create scan result with raw text (to test retention later)
        result = ScanResult(
            job_id=job.id,
            title="Analysis of Quantum Computing",
            overall_similarity_pct=12.5,
            exact_pct=6.0,
            near_pct=4.0,
            paraphrase_pct=2.5,
            total_words=1000,
            scored_words=950,
            matched_words=125,
            largest_single_source="arXiv:2105.1111 (5.2%)",
            raw_text="This is raw document text stored temporarily in memory.",
        )
        db.add(result)

        # Create certificate
        cert = Certificate(
            certificate_id="PC-2026-T9B2X4",
            token="token-abc-123",
            job_id=job.id,
            doc_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        db.add(cert)

        # Rate limit record
        rate = RateLimitRecord(
            key_hash="hash-user-test-123",
            scan_count=1,
            window_start=datetime.now(timezone.utc),
        )
        db.add(rate)
        db.commit()

        # Queries
        queried_user = db.scalar(select(User).where(User.email == "researcher@university.edu"))
        assert queried_user is not None
        assert len(queried_user.jobs) == 1

        queried_result = db.scalar(select(ScanResult).where(ScanResult.job_id == job.id))
        assert queried_result is not None
        assert queried_result.raw_text is not None

        queried_cert = db.scalar(select(Certificate).where(Certificate.certificate_id == "PC-2026-T9B2X4"))
        assert queried_cert is not None
        assert queried_cert.token == "token-abc-123"
