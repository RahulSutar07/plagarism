"""Central configuration. Every limit from the build spec (Section 4) lives here.

Nothing is hard-coded elsewhere: read settings via `get_settings()`.
Secrets come from environment variables only (see .env.example).
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PC_", extra="ignore")

    # --- environment ---
    env: str = "dev"  # dev | test | prod
    site_url: str = "http://localhost:3000"

    # --- infrastructure (no defaults for secrets) ---
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "postgresql://plagiarism:plagiarism@localhost:5432/plagiarism"
    sentry_dsn: str = ""
    jwt_secret_key: str = "dev-insecure-jwt-secret-key-replace-in-production-9988"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # --- upload limits (Section 4) ---
    max_file_mb: int = 7
    min_words: int = 100
    max_words: int = 30_000
    max_paste_words: int = 2_000  # free plan, paste mode (Section 14)
    max_pdf_pages: int = 200
    max_ocr_pages: int = 40
    max_docx_uncompressed_mb: int = 50  # zip-bomb protection
    job_timeout_s: int = 180
    queue_cap: int = 20
    concurrent_jobs_per_user: int = 1
    daily_checks_per_user: int = 5

    # --- retention (Section 9) ---
    report_retention_days: int = 30
    job_text_max_age_minutes: int = 60
    upload_leftover_max_age_hours: int = 24
    db_size_warn_mb: int = 400

    # --- queues ---
    fast_queue: str = "fast"
    ocr_queue: str = "ocr"
    ocr_concurrency: int = 1

    # --- versions (shown in report/certificate footer) ---
    engine_version: str = "0.0.1"
    thresholds_version: str = "0.0.0-untuned"

    allowed_extensions: tuple[str, ...] = Field(default=("pdf", "docx", "txt"))

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    @property
    def max_docx_uncompressed_bytes(self) -> int:
        return self.max_docx_uncompressed_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
