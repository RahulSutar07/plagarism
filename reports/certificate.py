"""Plagiarism Check Certificate PDF generator and verification token manager.

Generates formal, single-page verification certificates with unique Display ID (PC-YYYY-XXXXXX),
SHA-256 cryptographic integrity hash, and embedded QR code for public authenticity validation.
"""
from __future__ import annotations

import hashlib
import io
import random
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.config import get_settings
from app.schemas import CertificateRecord, ScanResultSummary
from app.wording import CERTIFICATE_DISCLAIMER, INSTITUTION_NOTE, POSITIONING
from worker.store import get_job_store


def generate_certificate_id(year: int | None = None) -> str:
    """Generate human-readable certificate display ID in format PC-YYYY-XXXXXX."""
    if year is None:
        year = datetime.now(timezone.utc).year
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    code = "".join(random.choices(alphabet, k=6))
    return f"PC-{year}-{code}"


def compute_integrity_hash(
    title: str,
    total_words: int,
    scored_words: int,
    overall_similarity_pct: float,
    timestamp: str,
) -> str:
    """Compute reproducible SHA-256 integrity hash across document metadata and scan metrics."""
    raw = f"{title.strip()}|{total_words}|{scored_words}|{overall_similarity_pct:.2f}|{timestamp}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_or_get_certificate(job_id: str, summary: ScanResultSummary) -> CertificateRecord:
    """Build and persist certificate record in job store for public lookup."""
    store = get_job_store()
    existing = store.get_certificate_by_job(job_id)
    if existing:
        return existing

    cert_id = generate_certificate_id()
    token = secrets.token_urlsafe(16)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    doc_hash = compute_integrity_hash(
        title=summary.title,
        total_words=summary.total_words,
        scored_words=summary.scored_words,
        overall_similarity_pct=summary.overall_similarity_pct,
        timestamp=timestamp,
    )

    primary_sources = [
        f"{s.label[:55]} ({s.percentage:.1f}%)"
        for s in summary.source_summaries[:3]
    ]

    cert = CertificateRecord(
        certificate_id=cert_id,
        token=token,
        job_id=job_id,
        doc_hash=doc_hash,
        title=summary.title,
        created_at=timestamp,
        overall_similarity_pct=summary.overall_similarity_pct,
        exact_pct=summary.exact_pct,
        near_pct=summary.near_pct,
        paraphrase_pct=summary.paraphrase_pct,
        total_words=summary.total_words,
        scored_words=summary.scored_words,
        is_partial=summary.is_partial,
        partial_reason=summary.partial_reason or "",
        primary_sources=primary_sources,
        flags=summary.flags,
    )

    store.save_certificate(cert)
    return cert


def _generate_qr_code_image(url: str) -> io.BytesIO:
    """Generate high-contrast QR code image stream."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=4,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _draw_certificate_border(canvas, doc):
    """Draw a double decorative border with academic seal colors."""
    canvas.saveState()
    # Outer navy border
    canvas.setStrokeColor(colors.HexColor("#1e3a8a"))
    canvas.setLineWidth(2.5)
    canvas.rect(24, 24, doc.pagesize[0] - 48, doc.pagesize[1] - 48)

    # Inner gold border
    canvas.setStrokeColor(colors.HexColor("#d97706"))
    canvas.setLineWidth(0.8)
    canvas.rect(28, 28, doc.pagesize[0] - 56, doc.pagesize[1] - 56)

    # Corner decorations
    canvas.setFillColor(colors.HexColor("#1e3a8a"))
    for x in [32, doc.pagesize[0] - 38]:
        for y in [32, doc.pagesize[1] - 38]:
            canvas.rect(x, y, 6, 6, fill=1, stroke=0)

    canvas.restoreState()


def generate_certificate_pdf(
    cert: CertificateRecord,
    output: str | Path | BinaryIO | None = None,
) -> bytes:
    """Render formal single-page PDF Certificate with verification QR code."""
    settings = get_settings()
    verify_url = f"{settings.site_url.rstrip('/')}/verify/{cert.token}"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=45,
        leftMargin=45,
        topMargin=45,
        bottomMargin=45,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "CertTitle",
        parent=styles["Heading1"],
        fontSize=20,
        leading=24,
        alignment=1,
        textColor=colors.HexColor("#1e3a8a"),
        fontName="Helvetica-Bold",
        spaceAfter=3,
    )
    subtitle_style = ParagraphStyle(
        "CertSubtitle",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        alignment=1,
        textColor=colors.HexColor("#475569"),
        spaceAfter=8,
    )
    id_style = ParagraphStyle(
        "CertId",
        parent=styles["Normal"],
        fontSize=11,
        leading=14,
        alignment=1,
        textColor=colors.HexColor("#0f172a"),
        fontName="Helvetica-Bold",
        spaceAfter=10,
    )
    body_style = ParagraphStyle(
        "CertBody",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#334155"),
    )
    section_title = ParagraphStyle(
        "CertSection",
        parent=styles["Normal"],
        fontSize=9.5,
        leading=12,
        textColor=colors.HexColor("#1e293b"),
        fontName="Helvetica-Bold",
        spaceBefore=6,
        spaceAfter=4,
    )
    disclaimer_style = ParagraphStyle(
        "CertDisclaimer",
        parent=styles["Normal"],
        fontSize=6.8,
        leading=9.2,
        textColor=colors.HexColor("#64748b"),
    )

    story = []

    # 1. Header & Display ID
    story.append(Paragraph("CERTIFICATE OF PRE-CHECK ANALYSIS", title_style))
    story.append(Paragraph(f"Plagiarism Pre-Check Integrity Service &bull; <i>{POSITIONING}</i>", subtitle_style))
    story.append(Paragraph(f"Certificate ID: <b>{cert.certificate_id}</b>", id_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cbd5e1"), spaceAfter=10))

    # Partial Scan Notice if applicable
    if cert.is_partial:
        warn_data = [[
            Paragraph(
                f"<b>PARTIAL SCAN ADVISORY:</b> {cert.partial_reason or 'Candidate search limit reached.'}",
                ParagraphStyle("Warn", parent=body_style, textColor=colors.HexColor("#92400e")),
            )
        ]]
        warn_t = Table(warn_data, colWidths=[522])
        warn_t.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fef3c7")),
                ("BORDER", (0, 0), (-1, -1), 1, colors.HexColor("#f59e0b")),
                ("PADDING", (0, 0), (-1, -1), 6),
            ])
        )
        story.append(warn_t)
        story.append(Spacer(1, 8))

    # 2. Document & Analysis Metadata Table
    meta_rows = [
        [
            Paragraph("<b>Document Title:</b>", body_style),
            Paragraph(cert.title, body_style),
            Paragraph("<b>Analysis Date (UTC):</b>", body_style),
            Paragraph(cert.created_at, body_style),
        ],
        [
            Paragraph("<b>Total Words:</b>", body_style),
            Paragraph(str(cert.total_words), body_style),
            Paragraph("<b>Scored Words:</b>", body_style),
            Paragraph(f"{cert.scored_words} ({cert.total_words - cert.scored_words} excluded)", body_style),
        ],
    ]
    meta_table = Table(meta_rows, colWidths=[95, 175, 115, 137])
    meta_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("PADDING", (0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )
    story.append(meta_table)
    story.append(Spacer(1, 10))

    # 3. Overall Similarity Score Breakdown Box
    sim_color = "#dc2626" if cert.overall_similarity_pct > 25 else "#d97706" if cert.overall_similarity_pct > 15 else "#16a34a"
    score_html = (
        f"<font size=22 color='{sim_color}'><b>{cert.overall_similarity_pct:.1f}%</b></font><br/>"
        f"<b>Overall Similarity</b>"
    )
    breakdown_html = (
        f"<b>Detailed Categorization:</b><br/>"
        f"&bull; <b>Exact Matches:</b> {cert.exact_pct:.1f}% (runs &ge; 8 contiguous words)<br/>"
        f"&bull; <b>Near Matches:</b> {cert.near_pct:.1f}% (minor edits & bridged gaps)<br/>"
        f"&bull; <b>Paraphrase Matches:</b> {cert.paraphrase_pct:.1f}% (dense semantic similarity)"
    )
    score_data = [[
        Paragraph(score_html, ParagraphStyle("CenterScore", parent=body_style, alignment=1)),
        Paragraph(breakdown_html, body_style),
    ]]
    score_table = Table(score_data, colWidths=[160, 362])
    score_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
            ("BORDER", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("PADDING", (0, 0), (-1, -1), 8),
        ])
    )
    story.append(score_table)
    story.append(Spacer(1, 8))

    # 4. Primary Reference Sources & Audit Flags
    story.append(Paragraph("Primary Matched Sources", section_title))
    if cert.primary_sources:
        src_text = "<br/>".join(f"&bull; {src}" for src in cert.primary_sources)
    else:
        src_text = "No significant reference matches found above detection thresholds."
    story.append(Paragraph(src_text, body_style))
    story.append(Spacer(1, 4))

    story.append(Paragraph("Evasion & Formatting Inspection", section_title))
    if cert.flags:
        flags_text = "<br/>".join(f"&bull; <b>FLAG:</b> {f}" for f in cert.flags)
    else:
        flags_text = "<b>Status: CLEAN</b> &mdash; No hidden zero-width characters, font homoglyphs, or abnormal spacing detected."
    story.append(Paragraph(flags_text, body_style))
    story.append(Spacer(1, 10))

    # 5. Public Verification Section with QR Code
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#cbd5e1"), spaceAfter=8))
    qr_buf = _generate_qr_code_image(verify_url)
    qr_image = RLImage(qr_buf, width=68, height=68)

    verif_text = (
        f"<b>AUTHENTICITY VERIFICATION & CRYPTOGRAPHIC HASH</b><br/>"
        f"Scan the QR code or navigate to: <font color='#2563eb'>{verify_url}</font><br/>"
        f"<b>SHA-256 Document Integrity Digest:</b><br/>"
        f"<font size=6.5 color='#0f172a'>{cert.doc_hash}</font><br/>"
        f"<font size=7 color='#64748b'>Plagiarism Pre-Check does not store document text. "
        f"The SHA-256 digest provides immutable mathematical proof linking this certificate to the author's file.</font>"
    )
    verif_table = Table([[qr_image, Paragraph(verif_text, body_style)]], colWidths=[76, 446])
    verif_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BORDER", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("PADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(verif_table)
    story.append(Spacer(1, 8))

    # 6. Mandatory Disclaimers & Reproducibility Footer
    disclaimer_text = (
        f"<b>Mandatory Notice:</b> This certificate confirms that the document was analyzed by Plagiarism Pre-Check "
        f"on the date indicated. It is not an institutional clearance certificate and does not guarantee that institutional "
        f"checks (such as Turnitin or iThenticate) will produce identical results.<br/>"
        f"<b>Disclaimer:</b> {CERTIFICATE_DISCLAIMER} {INSTITUTION_NOTE}"
    )
    story.append(Paragraph(disclaimer_text, disclaimer_style))
    story.append(Spacer(1, 4))

    footer_text = (
        f"Plagiarism Pre-Check Engine v{settings.engine_version} | "
        f"Thresholds v{settings.thresholds_version} | "
        f"Certificate Spec v1.0 | Issued: {cert.created_at}"
    )
    story.append(Paragraph(footer_text, ParagraphStyle("Foot", parent=disclaimer_style, alignment=1)))

    doc.build(story, onFirstPage=_draw_certificate_border)
    pdf_bytes = buf.getvalue()

    if output:
        if isinstance(output, (str, Path)):
            Path(output).write_bytes(pdf_bytes)
        else:
            output.write(pdf_bytes)

    return pdf_bytes
