"""Server-side upload and content validation module.

Enforces strict magic-byte verification, file size limits, word count limits,
and document format policies.
"""
from __future__ import annotations

from pathlib import Path
from app.config import get_settings


class ValidationError(Exception):
    """Raised when an upload fails validation."""
    pass


def validate_file_magic_bytes(filename: str, content: bytes) -> str:
    """Validate file extension and magic bytes. Returns detected format ('pdf', 'docx', 'txt')."""
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise ValidationError(
                "File has .pdf extension but invalid PDF header (magic bytes mismatch)."
            )
        return "pdf"

    elif ext == ".docx":
        # ZIP magic bytes: PK\x03\x04
        if not content.startswith(b"PK\x03\x04"):
            raise ValidationError(
                "File has .docx extension but invalid DOCX/ZIP header (magic bytes mismatch)."
            )
        return "docx"

    elif ext == ".txt":
        # Check that it's decodable as text without binary null bytes
        if b"\x00" in content[:1024]:
            raise ValidationError("Binary or corrupted text file detected.")
        return "txt"

    else:
        raise ValidationError(
            f"Unsupported file format '{ext}'. Allowed extensions: .pdf, .docx, .txt"
        )


def validate_upload_limits(content: bytes, is_paste: bool = False) -> None:
    """Validate upload size against central configuration settings."""
    settings = get_settings()
    max_bytes = settings.max_file_bytes

    if len(content) > max_bytes:
        raise ValidationError(
            f"File size ({len(content) / (1024 * 1024):.2f} MB) exceeds maximum allowed limit ({settings.max_file_mb} MB)."
        )


def validate_word_counts(word_count: int, is_paste: bool = False) -> None:
    """Validate extracted word count meets minimum and maximum thresholds."""
    settings = get_settings()

    if word_count < settings.min_words:
        raise ValidationError(
            f"Document contains {word_count} words, which is under the minimum required threshold of {settings.min_words} words."
        )

    max_allowed = settings.max_paste_words if is_paste else settings.max_words
    if word_count > max_allowed:
        mode_str = "pasted text" if is_paste else "uploaded documents"
        raise ValidationError(
            f"Document contains {word_count} words, exceeding the maximum allowed limit of {max_allowed} words for {mode_str}."
        )
