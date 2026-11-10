"""Privacy-preserving rate limiting and concurrency enforcement.

Enforces:
1. Concurrency limit: Maximum 1 concurrent active scan per user (spec Section 4).
2. Daily volume limit: Maximum 5 scans per 24-hour window for free/anonymous users.
3. Anonymization: Client IP addresses are salted and hashed (never stored raw).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import RateLimitRecord, User
from worker.store import get_job_store

settings = get_settings()

_SALT = "plag-rate-limit-salt-2026"


def hash_client_ip(ip: str) -> str:
    """Hash client IP address with secret salt for GDPR/privacy compliance."""
    return hashlib.sha256(f"{ip}:{_SALT}".encode("utf-8")).hexdigest()[:32]


def get_client_ip(request: Request) -> str:
    """Extract real client IP address considering proxy headers in precedence order:
    1. CF-Connecting-IP (Cloudflare)
    2. X-Real-IP (nginx / reverse proxies)
    3. X-Forwarded-For (client IP is the first entry in comma-separated list)
    4. request.client.host (direct connection)
    """
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip and cf_ip.strip():
        return cf_ip.strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip and real_ip.strip():
        return real_ip.strip()
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded and forwarded.strip():
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def get_client_identifier(request: Request, user: User | None = None) -> tuple[str, str]:
    """Return (identifier_type, identifier_key_hash) for rate limiting."""
    if user:
        return "user", f"user:{user.id}"

    client_ip = get_client_ip(request)
    ip_hash = hash_client_ip(client_ip)
    return "ip", f"ip:{ip_hash}"


def enforce_auth_rate_limit(
    db: Session,
    key: str,
    max_requests: int,
    window_seconds: int,
    action_name: str = "request",
) -> None:
    """Sliding window rate limiter for authentication (login & registration).
    
    Protects against credential brute-forcing and mass registration per IP and per email.
    Raises HTTPException(429) if max_requests exceeded within window_seconds.
    """
    key_hash = hashlib.sha256(f"auth_rl:{key}:{_SALT}".encode("utf-8")).hexdigest()[:32]
    now = datetime.now(timezone.utc)
    window_start_limit = now - timedelta(seconds=window_seconds)

    record = db.scalars(
        select(RateLimitRecord)
        .where(RateLimitRecord.key_hash == key_hash)
        .where(RateLimitRecord.window_start >= window_start_limit)
        .order_by(RateLimitRecord.window_start.desc())
        .limit(1)
    ).first()

    if record:
        if record.scan_count >= max_requests:
            ws = record.window_start
            if ws.tzinfo is None:
                ws = ws.replace(tzinfo=timezone.utc)
            elapsed = (now - ws).total_seconds()
            retry_after = max(1, int(window_seconds - elapsed))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many {action_name} attempts. Please try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )
        record.scan_count += 1
        db.commit()
    else:
        new_record = RateLimitRecord(
            key_hash=key_hash,
            scan_count=1,
            window_start=now,
        )
        db.add(new_record)
        db.commit()


def enforce_concurrency_limit(identifier: str, user_id: int | None = None) -> None:
    """Ensure user does not have multiple active scans simultaneously."""
    store = get_job_store()
    with store._lock:
        active_count = 0
        for job in store._jobs.values():
            if job.status in ("queued", "processing"):
                # If identifier is attached to job in store or matching user
                if getattr(job, "identifier", None) == identifier:
                    active_count += 1

    if active_count >= settings.concurrent_jobs_per_user:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You already have an active scan in progress. Only 1 concurrent scan is permitted per user.",
            headers={"Retry-After": "30"},
        )


def check_and_increment_rate_limit(
    db: Session,
    key_hash: str,
    tier: str = "free",
) -> int:
    """Check 24-hour scan quota and record new request. Returns remaining scans."""
    if tier == "pro":
        return 999999

    now = datetime.now(timezone.utc)
    window_start_limit = now - timedelta(hours=24)

    record = db.scalars(
        select(RateLimitRecord)
        .where(RateLimitRecord.key_hash == key_hash)
        .where(RateLimitRecord.window_start >= window_start_limit)
        .order_by(RateLimitRecord.window_start.desc())
        .limit(1)
    ).first()

    max_scans = settings.daily_checks_per_user

    if record:
        if record.scan_count >= max_scans:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Daily scan limit reached ({max_scans} checks per 24 hours). Please try again tomorrow or sign up for an academic license.",
                headers={"Retry-After": "3600"},
            )
        record.scan_count += 1
        db.commit()
        return max(0, max_scans - record.scan_count)
    else:
        new_record = RateLimitRecord(
            key_hash=key_hash,
            scan_count=1,
            window_start=now,
        )
        db.add(new_record)
        db.commit()
        return max(0, max_scans - 1)
