import pytest
from app.database import SessionLocal
from app.models import RateLimitRecord
from sqlalchemy import delete

@pytest.fixture(autouse=True)
def clean_test_rate_limits():
    """Clear rate limit records for test suite executions to avoid cross-test contamination."""
    try:
        with SessionLocal() as db:
            db.execute(delete(RateLimitRecord))
            db.commit()
    except Exception:
        pass
    yield
