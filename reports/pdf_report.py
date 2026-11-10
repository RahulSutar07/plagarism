"""PDF Plagiarism Report Generator using ReportLab.

Generates academic-grade similarity reports featuring overall scores, Exact/Near/Paraphrase breakdowns,
source contribution tables, evasion flags, partial-scan notices, and mandatory institutional disclaimers.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import get_settings
from app.schemas import ScanResultSummary
from app.wording import INSTITUTION_NOTE, POSITIONING, REPORT_DISCLAIMER


def generate_pdf_report(
    summary: ScanResultSummary,
    output: str | Path | BinaryIO | None = None,
) -> bytes:
    """Generate professional PDF similarity report for a completed plagiarism scan."""
    settings = get_settings()
    buf = io.BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=12,
    )
    section_heading = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=14,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#334155"),
    )
    disclaimer_style = ParagraphStyle(
        "Disclaimer",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#475569"),
    )
    footer_style = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontSize=7,
        leading=10,
        textColor=colors.HexColor("#94a3b8"),
    )

    story = []

    # 1. Header Banner
    story.append(Paragraph("Plagiarism Pre-Check Report", title_style))
    story.append(Paragraph(f"<i>{POSITIONING}</i>", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#2563eb"), spaceAfter=12))

    # Partial Scan Notice
    if summary.is_partial:
        partial_data = [[
            Paragraph(
                f"<b>PARTIAL SCAN NOTICE:</b> {summary.partial_reason}",
                ParagraphStyle("Warning", parent=body_style, textColor=colors.HexColor("#92400e")),
            )
        ]]
        partial_table = Table(partial_data, colWidths=[530])
        partial_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fef3c7")),
                ("BORDER", (0, 0), (-1, -1), 1, colors.HexColor("#f59e0b")),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ])
        )
        story.append(partial_table)
        story.append(Spacer(1, 10))

    # 2. Executive Summary Metrics Box
    scan_date = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    meta_text = (
        f"<b>Document:</b> {summary.title}<br/>"
        f"<b>Scan Date:</b> {scan_date}<br/>"
        f"<b>Total Words:</b> {summary.total_words} | <b>Scored Words:</b> {summary.scored_words} "
        f"({summary.total_words - summary.scored_words} excluded)"
    )

    sim_color = "#dc2626" if summary.overall_similarity_pct > 25 else "#d97706" if summary.overall_similarity_pct > 15 else "#16a34a"
    score_display = (
        f"<font size=24 color='{sim_color}'><b>{summary.overall_similarity_pct:.1f}%</b></font><br/>"
        f"<b>Overall Similarity</b><br/>"
        f"<font size=8 color='#64748b'>Exact: {summary.exact_pct:.1f}% | Near: {summary.near_pct:.1f}% | Para: {summary.paraphrase_pct:.1f}%</font>"
    )

    summary_data = [
        [Paragraph(meta_text, body_style), Paragraph(score_display, ParagraphStyle("Score", parent=body_style, alignment=1))]
    ]
    summary_table = Table(summary_data, colWidths=[350, 180])
    summary_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BORDER", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ])
    )
    story.append(summary_table)

    # 3. Matched Sources Table
    story.append(Paragraph("Matched Reference Sources", section_heading))
    if summary.source_summaries:
        source_rows = [
            ["#", "Source Title / URL", "Type", "Words", "Contribution", "Confidence"]
        ]
        for idx, src in enumerate(summary.source_summaries[:15], 1):
            source_rows.append([
                str(idx),
                Paragraph(src.label[:65] + ("..." if len(src.label) > 65 else ""), body_style),
                src.kind,
                str(src.matched_words),
                f"{src.percentage:.1f}%",
                src.confidence.capitalize(),
            ])

        src_table = Table(source_rows, colWidths=[25, 270, 55, 55, 65, 60])
        src_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("TOPPADDING", (0, 0), (-1, 0), 6),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (3, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ])
        )
        story.append(src_table)
    else:
        story.append(Paragraph("No significant matching sources were found above detection thresholds.", body_style))

    # 4. Filters & Audit Flags
    story.append(Paragraph("Applied Filters & Evasion Audit", section_heading))
    filter_info = (
        "<b>Exclusions Applied:</b> References/Bibliography section, properly quoted and cited material, "
        "and short matching sequences under 8 words.<br/>"
        f"<b>Sources Searched:</b> {summary.searched_description}<br/>"
        f"<b>Largest Single Source:</b> {summary.largest_single_source}"
    )
    story.append(Paragraph(filter_info, body_style))
    story.append(Spacer(1, 6))

    if summary.flags:
        flags_text = "<b>Audit Flags Detected:</b><br/>" + "<br/>".join(f"• {f}" for f in summary.flags)
    else:
        flags_text = "<b>Audit Flags Detected:</b> None (document follows standard formatting without detected evasion tactics)."
    story.append(Paragraph(flags_text, body_style))

    # 5. Mandatory Disclaimer & Reproducibility Footer
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=8))
    story.append(Paragraph(f"<b>Disclaimer:</b> {REPORT_DISCLAIMER}", disclaimer_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"<b>Notice:</b> {INSTITUTION_NOTE}", disclaimer_style))
    story.append(Spacer(1, 8))

    reproducibility = (
        f"Plagiarism Pre-Check Engine v{settings.engine_version} | "
        f"Thresholds v{settings.thresholds_version} | "
        f"Model: all-MiniLM-L6-v2 | Shingle N=5 | Min Run=8 words | {scan_date}"
    )
    story.append(Paragraph(reproducibility, footer_style))

    doc.build(story)
    pdf_bytes = buf.getvalue()

    if output:
        if isinstance(output, (str, Path)):
            Path(output).write_bytes(pdf_bytes)
        else:
            output.write(pdf_bytes)

    return pdf_bytes
