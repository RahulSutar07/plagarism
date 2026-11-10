"""SQLAlchemy database models for persistence, authentication, and compliance.

Adheres strictly to the data minimization specification: raw document text
is stored in a nullable column designed to be purged 1 hour after processing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    """User account model supporting free & pro tiers."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="user", nullable=False)
    tier: Mapped[str] = mapped_column(String(50), default="free", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    jobs: Mapped[list[Job]] = relationship("Job", back_populates="user", cascade="all, delete-orphan")


class Job(Base):
    """Asynchronous plagiarism check job record."""
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    stage: Mapped[str] = mapped_column(String(32), default="sanitizing", nullable=False)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    queue_name: Mapped[str] = mapped_column(String(32), default="fast", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    user: Mapped[User | None] = relationship("User", back_populates="jobs")
    result: Mapped[ScanResult | None] = relationship("ScanResult", back_populates="job", uselist=False, cascade="all, delete-orphan")
    certificates: Mapped[list[Certificate]] = relationship("Certificate", back_populates="job", cascade="all, delete-orphan")


class ScanResult(Base):
    """Completed scan results with nullable raw text for 1-hour privacy purge."""
    __tablename__ = "scan_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="Document", nullable=False)
    overall_similarity_pct: Mapped[float] = mapped_column(Float, nullable=False)
    exact_pct: Mapped[float] = mapped_column(Float, nullable=False)
    near_pct: Mapped[float] = mapped_column(Float, nullable=False)
    paraphrase_pct: Mapped[float] = mapped_column(Float, nullable=False)
    total_words: Mapped[int] = mapped_column(Integer, nullable=False)
    scored_words: Mapped[int] = mapped_column(Integer, nullable=False)
    matched_words: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    largest_single_source: Mapped[str] = mapped_column(String(255), default="None", nullable=False)
    is_partial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    partial_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    searched_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    flags_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    sources_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    spans_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # NULLED after 1 hour retention
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    job: Mapped[Job] = relationship("Job", back_populates="result")

    def get_flags(self) -> list[str]:
        return json.loads(self.flags_json) if self.flags_json else []

    def get_sources(self) -> list[dict[str, Any]]:
        return json.loads(self.sources_json) if self.sources_json else []


class Certificate(Base):
    """Formal verification certificate record."""
    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    certificate_id: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    doc_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    job: Mapped[Job] = relationship("Job", back_populates="certificates")


class RateLimitRecord(Base):
    """Daily request counts indexed by cryptographic hash of user ID or IP."""
    __tablename__ = "rate_limit_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    scan_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AuditLog(Base):
    """Audit log tracking system events with salted IP anonymization."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ip_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
