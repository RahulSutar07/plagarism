"""Report generation package.

Provides PDF similarity reports and verification certificates.
"""
from reports.certificate import (
    compute_integrity_hash,
    create_or_get_certificate,
    generate_certificate_id,
    generate_certificate_pdf,
)
from reports.pdf_report import generate_pdf_report

__all__ = [
    "generate_pdf_report",
    "generate_certificate_pdf",
    "create_or_get_certificate",
    "generate_certificate_id",
    "compute_integrity_hash",
]

