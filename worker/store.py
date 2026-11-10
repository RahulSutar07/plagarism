"""Job store and queue state manager.

Stores active job statuses, progress stages, and final scan results with
thread-safe in-memory caching and persistent SQLAlchemy database synchronization.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.schemas import (
    CertificateRecord,
    JobStage,
    JobStatus,
    MatchSpanSchema,
    ScanResultSummary,
    SourceSummarySchema,
)

logger = logging.getLogger(__name__)


@dataclass
class JobRecord:
    job_id: str
    status: JobStatus = "queued"
    stage: JobStage = "sanitizing"
    progress_pct: int = 0
    created_at: float = field(default_factory=time.time)
    error: str | None = None
    result: ScanResultSummary | None = None
    queue_name: str = "fast"
    identifier: str | None = None
    user_id: int | None = None


class JobStore:
    """Thread-safe job store managing job lifecycle, status polling, and database persistence."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, JobRecord] = {}
        self._certificates_by_token: dict[str, CertificateRecord] = {}
        self._certificates_by_id: dict[str, CertificateRecord] = {}
        self._certificates_by_job: dict[str, CertificateRecord] = {}

    def create_job(
        self,
        queue_name: str = "fast",
        identifier: str | None = None,
        user_id: int | None = None,
    ) -> str:
        """Create and register a new queued job in memory and in the database."""
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        record = JobRecord(
            job_id=job_id,
            queue_name=queue_name,
            identifier=identifier,
            user_id=user_id,
        )

        with self._lock:
            self._jobs[job_id] = record

        # Persist to database
        try:
            from app.database import SessionLocal
            from app.models import Job as DBJob

            with SessionLocal() as db:
                db_job = DBJob(
                    id=job_id,
                    user_id=user_id,
                    status="queued",
                    stage="sanitizing",
                    progress_pct=0,
                    queue_name=queue_name,
                )
                db.add(db_job)
                db.commit()
        except Exception as e:
            logger.debug("Database sync on create_job (%s): %s", job_id, e)

        return job_id

    def update_job(
        self,
        job_id: str,
        status: JobStatus | None = None,
        stage: JobStage | None = None,
        progress_pct: int | None = None,
        error: str | None = None,
        result: ScanResultSummary | None = None,
    ) -> None:
        """Update job progress or final outcome in memory and database."""
        with self._lock:
            if job_id not in self._jobs:
                # Attempt to recover from DB before giving up
                recovered = self._load_job_from_db(job_id)
                if not recovered:
                    return
            rec = self._jobs[job_id]
            if status is not None:
                rec.status = status
            if stage is not None:
                rec.stage = stage
            if progress_pct is not None:
                rec.progress_pct = progress_pct
            if error is not None:
                rec.error = error
            if result is not None:
                rec.result = result

        # Persist to database
        try:
            from app.database import SessionLocal
            from app.models import Job as DBJob, ScanResult as DBScanResult

            with SessionLocal() as db:
                db_job = db.get(DBJob, job_id)
                if db_job:
                    if status is not None:
                        db_job.status = status
                    if stage is not None:
                        db_job.stage = stage
                    if progress_pct is not None:
                        db_job.progress_pct = progress_pct
                    if error is not None:
                        db_job.error = error

                    if result is not None:
                        flags_json = json.dumps(result.flags)
                        sources_json = json.dumps([s.model_dump() for s in result.source_summaries])
                        spans_json = json.dumps([s.model_dump() for s in result.match_spans])

                        existing_res = db.query(DBScanResult).filter_by(job_id=job_id).first()
                        if not existing_res:
                            db_res = DBScanResult(
                                job_id=job_id,
                                title=result.title,
                                overall_similarity_pct=result.overall_similarity_pct,
                                exact_pct=result.exact_pct,
                                near_pct=result.near_pct,
                                paraphrase_pct=result.paraphrase_pct,
                                total_words=result.total_words,
                                scored_words=result.scored_words,
                                matched_words=result.matched_words,
                                largest_single_source=result.largest_single_source,
                                is_partial=result.is_partial,
                                partial_reason=result.partial_reason,
                                searched_description=result.searched_description,
                                flags_json=flags_json,
                                sources_json=sources_json,
                                spans_json=spans_json,
                                raw_text=result.cleaned_text,
                            )
                            db.add(db_res)
                        else:
                            existing_res.title = result.title
                            existing_res.overall_similarity_pct = result.overall_similarity_pct
                            existing_res.exact_pct = result.exact_pct
                            existing_res.near_pct = result.near_pct
                            existing_res.paraphrase_pct = result.paraphrase_pct
                            existing_res.total_words = result.total_words
                            existing_res.scored_words = result.scored_words
                            existing_res.matched_words = result.matched_words
                            existing_res.largest_single_source = result.largest_single_source
                            existing_res.is_partial = result.is_partial
                            existing_res.partial_reason = result.partial_reason
                            existing_res.searched_description = result.searched_description
                            existing_res.flags_json = flags_json
                            existing_res.sources_json = sources_json
                            existing_res.spans_json = spans_json
                            existing_res.raw_text = result.cleaned_text

                    db.commit()
        except Exception as e:
            logger.debug("Database sync on update_job (%s): %s", job_id, e)

    def _load_job_from_db(self, job_id: str) -> JobRecord | None:
        """Internal helper to load a job record and result from the database."""
        try:
            from app.database import SessionLocal
            from app.models import Job as DBJob

            with SessionLocal() as db:
                db_job = db.get(DBJob, job_id)
                if not db_job:
                    return None

                summary = None
                if db_job.result:
                    r = db_job.result
                    try:
                        flags = json.loads(r.flags_json) if r.flags_json else []
                    except Exception:
                        flags = []

                    try:
                        sources_raw = json.loads(r.sources_json) if r.sources_json else []
                        source_summaries = [SourceSummarySchema(**s) for s in sources_raw]
                    except Exception:
                        source_summaries = []

                    try:
                        spans_raw = json.loads(r.spans_json) if r.spans_json else []
                        match_spans = [MatchSpanSchema(**m) for m in spans_raw]
                    except Exception:
                        match_spans = []

                    summary = ScanResultSummary(
                        title=r.title,
                        overall_similarity_pct=r.overall_similarity_pct,
                        exact_pct=r.exact_pct,
                        near_pct=r.near_pct,
                        paraphrase_pct=r.paraphrase_pct,
                        total_words=r.total_words,
                        scored_words=r.scored_words,
                        matched_words=r.matched_words,
                        largest_single_source=r.largest_single_source,
                        is_partial=r.is_partial,
                        partial_reason=r.partial_reason or "",
                        searched_description=r.searched_description or "",
                        flags=flags,
                        source_summaries=source_summaries,
                        match_spans=match_spans,
                        cleaned_text=r.raw_text or "",
                    )

                created_ts = db_job.created_at.timestamp() if db_job.created_at else time.time()
                record = JobRecord(
                    job_id=db_job.id,
                    status=db_job.status,  # type: ignore
                    stage=db_job.stage,    # type: ignore
                    progress_pct=db_job.progress_pct,
                    created_at=created_ts,
                    error=db_job.error,
                    result=summary,
                    queue_name=db_job.queue_name,
                    user_id=db_job.user_id,
                )
                self._jobs[job_id] = record
                return record
        except Exception as e:
            logger.debug("Database load error for job %s: %s", job_id, e)
            return None

    def get_job(self, job_id: str) -> JobRecord | None:
        """Retrieve job record by ID from memory or fall back to the database."""
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is not None:
                return rec
            return self._load_job_from_db(job_id)

    def get_queue_position(self, job_id: str) -> int:
        """Calculate number of jobs ahead in the queue."""
        with self._lock:
            target = self._jobs.get(job_id)
            if not target or target.status != "queued":
                return 0
            pos = 1
            for j in self._jobs.values():
                if j.status == "queued" and j.created_at < target.created_at:
                    pos += 1
            return pos

    def get_waiting_count(self) -> int:
        """Return total number of currently queued jobs."""
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.status == "queued")

    def save_certificate(self, cert: CertificateRecord) -> None:
        """Store certificate record in memory and database."""
        with self._lock:
            self._certificates_by_token[cert.token] = cert
            self._certificates_by_id[cert.certificate_id] = cert
            self._certificates_by_job[cert.job_id] = cert

        try:
            from app.database import SessionLocal
            from app.models import Certificate as DBCertificate

            with SessionLocal() as db:
                existing = db.query(DBCertificate).filter_by(certificate_id=cert.certificate_id).first()
                if not existing:
                    db_cert = DBCertificate(
                        certificate_id=cert.certificate_id,
                        token=cert.token,
                        job_id=cert.job_id,
                        doc_hash=cert.doc_hash,
                        is_active=True,
                    )
                    db.add(db_cert)
                    db.commit()
        except Exception as e:
            logger.debug("Database sync on save_certificate: %s", e)

    def _load_certificate_from_db(
        self,
        token: str | None = None,
        cert_id: str | None = None,
        job_id: str | None = None,
    ) -> CertificateRecord | None:
        """Reconstruct certificate record from database."""
        try:
            from app.database import SessionLocal
            from app.models import Certificate as DBCertificate

            with SessionLocal() as db:
                query = db.query(DBCertificate)
                if token:
                    db_cert = query.filter_by(token=token).first()
                elif cert_id:
                    db_cert = query.filter_by(certificate_id=cert_id).first()
                elif job_id:
                    db_cert = query.filter_by(job_id=job_id).first()
                else:
                    return None

                if not db_cert or not db_cert.job:
                    return None

                job_rec = self.get_job(db_cert.job_id)
                summary = job_rec.result if job_rec else None

                timestamp = db_cert.created_at.strftime("%Y-%m-%d %H:%M UTC") if db_cert.created_at else ""

                primary_sources = []
                if summary:
                    primary_sources = [
                        f"{s.label[:55]} ({s.percentage:.1f}%)"
                        for s in summary.source_summaries[:3]
                    ]

                cert = CertificateRecord(
                    certificate_id=db_cert.certificate_id,
                    token=db_cert.token,
                    job_id=db_cert.job_id,
                    doc_hash=db_cert.doc_hash,
                    title=summary.title if summary else "Document",
                    created_at=timestamp,
                    overall_similarity_pct=summary.overall_similarity_pct if summary else 0.0,
                    exact_pct=summary.exact_pct if summary else 0.0,
                    near_pct=summary.near_pct if summary else 0.0,
                    paraphrase_pct=summary.paraphrase_pct if summary else 0.0,
                    total_words=summary.total_words if summary else 0,
                    scored_words=summary.scored_words if summary else 0,
                    is_partial=summary.is_partial if summary else False,
                    partial_reason=summary.partial_reason or "" if summary else "",
                    primary_sources=primary_sources,
                    flags=summary.flags if summary else [],
                )

                self._certificates_by_token[cert.token] = cert
                self._certificates_by_id[cert.certificate_id] = cert
                self._certificates_by_job[cert.job_id] = cert
                return cert
        except Exception as e:
            logger.debug("Database load error for certificate: %s", e)
            return None

    def get_certificate_by_token(self, token: str) -> CertificateRecord | None:
        """Look up certificate by public verification token."""
        with self._lock:
            rec = self._certificates_by_token.get(token)
            if rec is not None:
                return rec
            return self._load_certificate_from_db(token=token)

    def get_certificate_by_id(self, cert_id: str) -> CertificateRecord | None:
        """Look up certificate by display ID (PC-YYYY-XXXXXX)."""
        with self._lock:
            rec = self._certificates_by_id.get(cert_id)
            if rec is not None:
                return rec
            return self._load_certificate_from_db(cert_id=cert_id)

    def get_certificate_by_job(self, job_id: str) -> CertificateRecord | None:
        """Look up certificate by original job ID."""
        with self._lock:
            rec = self._certificates_by_job.get(job_id)
            if rec is not None:
                return rec
            return self._load_certificate_from_db(job_id=job_id)


_global_job_store = JobStore()


def get_job_store() -> JobStore:
    return _global_job_store
