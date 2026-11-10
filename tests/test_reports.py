"""Unit tests for PDF plagiarism report generation."""
import io
from pathlib import Path

from app.schemas import ScanResultSummary, SourceSummarySchema
from reports.pdf_report import generate_pdf_report


def make_sample_summary(is_partial: bool = False, flags: list[str] | None = None) -> ScanResultSummary:
    return ScanResultSummary(
        title="Comparative Analysis of Neural Architectures",
        overall_similarity_pct=18.5,
        exact_pct=10.2,
        near_pct=5.1,
        paraphrase_pct=3.2,
        total_words=1250,
        scored_words=1100,
        matched_words=169,
        is_partial=is_partial,
        partial_reason="Candidate query limit reached during web search." if is_partial else "",
        largest_single_source="arXiv:2104.09864 (8.4%)",
        searched_description="Worker reference corpus (1,500 docs) + DuckDuckGo Web API",
        source_summaries=[
            SourceSummarySchema(
                source_id=1,
                label="https://arxiv.org/abs/2104.09864",
                kind="web",
                matched_words=105,
                percentage=8.4,
                confidence="high",
                longest_contiguous_run=18,
            ),
            SourceSummarySchema(
                source_id=2,
                label="Local Corpus: Deep Learning Handbook (2022)",
                kind="corpus",
                matched_words=64,
                percentage=5.1,
                confidence="medium",
                longest_contiguous_run=12,
            ),
        ],
        flags=flags or ["Zero-width spaces detected and stripped (3 instances)."],
        match_spans=[],
    )


def test_generate_pdf_report_bytes():
    summary = make_sample_summary()
    pdf_bytes = generate_pdf_report(summary)

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF-")


def test_generate_pdf_report_to_file(tmp_path: Path):
    summary = make_sample_summary(is_partial=True)
    target_file = tmp_path / "test_report.pdf"

    pdf_bytes = generate_pdf_report(summary, output=target_file)
    assert target_file.exists()
    assert target_file.stat().st_size == len(pdf_bytes)
    assert target_file.read_bytes().startswith(b"%PDF-")


def test_generate_pdf_report_to_stream():
    summary = make_sample_summary(flags=[])
    buf = io.BytesIO()

    pdf_bytes = generate_pdf_report(summary, output=buf)
    buf.seek(0)
    stream_content = buf.read()
    assert stream_content == pdf_bytes
    assert stream_content.startswith(b"%PDF-")
