"""Unit and integration tests for concurrency protection and 24-hour rate limiting."""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.rate_limit import (
    check_and_increment_rate_limit,
    enforce_concurrency_limit,
    hash_client_ip,
)
from worker.store import get_job_store


def test_hash_client_ip():
    ip1 = "192.168.1.100"
    ip2 = "192.168.1.101"
    h1 = hash_client_ip(ip1)
    h2 = hash_client_ip(ip1)
    h3 = hash_client_ip(ip2)

    assert len(h1) == 32
    assert h1 == h2
    assert h1 != h3
    # Anonymity verification: raw IP should never appear in hash
    assert ip1 not in h1


def test_concurrency_limit_enforcement():
    store = get_job_store()
    ident = "test-user-concurrency-1"

    # No active jobs -> passes
    enforce_concurrency_limit(ident)

    # 1 active job created in queue
    store.create_job(identifier=ident)

    # 2nd concurrent request must raise 429
    with pytest.raises(HTTPException) as exc_info:
        enforce_concurrency_limit(ident)

    assert exc_info.value.status_code == 429
    assert "active scan in progress" in exc_info.value.detail


def test_daily_rate_limit_free_and_pro_tier():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionTest = sessionmaker(bind=engine)

    key = "user:42"

    with SessionTest() as db:
        # First 5 scans should succeed
        for i in range(5):
            rem = check_and_increment_rate_limit(db, key, tier="free")
            assert rem == max(0, 4 - i)

        # 6th scan must raise 429 Too Many Requests
        with pytest.raises(HTTPException) as exc_info:
            check_and_increment_rate_limit(db, key, tier="free")

        assert exc_info.value.status_code == 429
        assert "Daily scan limit reached" in exc_info.value.detail

        # Pro tier account bypasses daily quota
        rem_pro = check_and_increment_rate_limit(db, "user:99", tier="pro")
        assert rem_pro > 1000
