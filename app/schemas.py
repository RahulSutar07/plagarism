"""Pydantic schemas for request and response validation."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field

JobStatus = Literal["queued", "processing", "completed", "failed"]
JobStage = Literal["extracting", "sanitizing", "retrieving", "matching", "completed", "failed"]


class PasteSubmissionRequest(BaseModel):
    text: str = Field(..., min_length=50, description="Pasted text content to check")
    title: str = Field(default="Pasted Document", max_length=150, description="Document title")
    enable_web_search: bool = Field(default=False, description="Search open web sources")
    enable_paraphrase: bool = Field(default=True, description="Enable neural paraphrase detection")


class JobSubmissionResponse(BaseModel):
    job_id: str
    status: JobStatus
    queue_position: int
    estimated_wait_seconds: int
    message: str


class SourceSummarySchema(BaseModel):
    source_id: int
    label: str
    kind: str
    matched_words: int
    percentage: float
    confidence: Literal["high", "medium", "low"]
    longest_contiguous_run: int


class MatchSpanSchema(BaseModel):
    start_token_idx: int
    end_token_idx: int
    start_char: int
    end_char: int
    source_id: int
    match_type: Literal["exact", "near", "paraphrase"]
    matched_word_count: int


class ScanResultSummary(BaseModel):
    title: str
    overall_similarity_pct: float
    exact_pct: float
    near_pct: float
    paraphrase_pct: float
    total_words: int
    scored_words: int
    matched_words: int
    largest_single_source: str
    is_partial: bool
    partial_reason: str
    searched_description: str
    flags: list[str]
    source_summaries: list[SourceSummarySchema]
    match_spans: list[MatchSpanSchema]
    cleaned_text: str | None = None  # Returned to client for highlight reconstruction


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    stage: JobStage
    progress_pct: int
    queue_position: int | None = None
    error: str | None = None
    result: ScanResultSummary | None = None
    certificate_id: str | None = None
    verification_token: str | None = None


class CertificateRecord(BaseModel):
    certificate_id: str = Field(..., description="Unique ID in format PC-YYYY-XXXXXX")
    token: str = Field(..., description="Verification lookup token")
    job_id: str
    doc_hash: str = Field(..., description="SHA-256 integrity hash")
    title: str
    created_at: str
    overall_similarity_pct: float
    exact_pct: float
    near_pct: float
    paraphrase_pct: float
    total_words: int
    scored_words: int
    is_partial: bool
    partial_reason: str = ""
    primary_sources: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class CertificateVerificationResponse(BaseModel):
    verified: bool
    certificate_id: str
    title: str
    created_at: str
    overall_similarity_pct: float
    exact_pct: float
    near_pct: float
    paraphrase_pct: float
    total_words: int
    scored_words: int
    doc_hash: str
    primary_sources: list[str] = Field(default_factory=list)
    is_partial: bool
    partial_reason: str = ""
    flags: list[str] = Field(default_factory=list)
    notice: str = (
        "Plagiarism Pre-Check does not store document text. The document hash "
        "allows the author to prove this certificate corresponds to their file."
    )
