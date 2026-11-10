"""Data minimization and privacy retention cleaner.

Enforces:
1. Purges raw document text from the database 1 hour after processing (spec Section 9).
2. Deletes expired scan results older than 30 days.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Job, ScanResult

logger = logging.getLogger(__name__)
settings = get_settings()


def purge_expired_raw_texts(db: Session, max_age_minutes: int | None = None) -> int:
    """Null out raw document text for all scans older than max_age_minutes (default: 60m)."""
    age_limit = max_age_minutes or settings.job_text_max_age_minutes
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=age_limit)

    stmt = (
        update(ScanResult)
        .where(ScanResult.created_at <= cutoff)
        .where(ScanResult.raw_text.is_not(None))
        .values(raw_text=None)
    )
    result = db.execute(stmt)
    db.commit()
    count = result.rowcount
    if count > 0:
        logger.info("Privacy retention purge: nulled raw document text on %d scans.", count)
    return count


def purge_expired_scan_records(db: Session, max_age_days: int | None = None) -> int:
    """Delete scan records older than report retention policy (default: 30 days)."""
    retention_days = max_age_days or settings.report_retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    stmt = delete(Job).where(Job.created_at <= cutoff)
    result = db.execute(stmt)
    db.commit()
    count = result.rowcount
    if count > 0:
        logger.info("Retention purge: deleted %d expired job records.", count)
    return count


def run_retention_sweep(db: Session) -> dict[str, int]:
    """Execute full data minimization retention sweep."""
    nulled_texts = purge_expired_raw_texts(db)
    purged_jobs = purge_expired_scan_records(db)
    return {
        "nulled_raw_texts": nulled_texts,
        "purged_expired_jobs": purged_jobs,
    }


def main() -> None:
    """CLI daemon entry point for the periodic retention cleaner."""
    import time
    from app.database import SessionLocal

    logging.basicConfig(level=logging.INFO)
    logger.info("Starting Plagiarism Pre-Check Data Minimization Retention Cleaner daemon...")
    while True:
        try:
            with SessionLocal() as db:
                stats = run_retention_sweep(db)
                logger.info("Retention sweep complete: %s", stats)
        except Exception as e:
            logger.error("Retention cleaner encountered error: %s", e)
        time.sleep(900)  # 15 minute interval


if __name__ == "__main__":
    main()

