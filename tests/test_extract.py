import io
import zipfile
import pytest

from pipeline.extract import (
    ExtractionError,
    extract_document,
    extract_text_from_docx,
    extract_text_from_pdf,
    extract_text_from_txt,
)


def test_extract_txt_string_and_bytes():
    raw = "This is a simple academic text for testing extraction."
    res1 = extract_text_from_txt(raw)
    assert res1 == raw

    res2 = extract_text_from_txt(raw.encode("utf-8"))
    assert res2 == raw


def test_extract_docx_with_paragraphs_and_tables(tmp_path):
    from docx import Document

    doc_path = tmp_path / "sample.docx"
    doc = Document()
    doc.add_paragraph("First paragraph of research document.")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Header 1"
    table.cell(0, 1).text = "Header 2"
    table.cell(1, 0).text = "Value A"
    table.cell(1, 1).text = "Value B"
    doc.save(str(doc_path))

    extracted = extract_text_from_docx(doc_path)
    assert "First paragraph of research document." in extracted
    assert "Header 1" in extracted
    assert "Value B" in extracted


def test_docx_zip_bomb_protection():
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Create an entry whose uncompressed size exceeds limit
        zf.writestr("word/document.xml", b"0" * 2000)

    bio.seek(0)
    # Set limit to 1000 bytes
    with pytest.raises(ExtractionError, match="exceeds safety limit"):
        extract_text_from_docx(bio, max_uncompressed_bytes=1000)


def test_extract_pdf_pages_and_limit(tmp_path):
    import fitz

    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((50, 50), "This is page one text of research paper.")
    page2 = doc.new_page()
    page2.insert_text((50, 50), "This is page two text of research paper.")
    doc.save(str(pdf_path))
    doc.close()

    text, page_count = extract_text_from_pdf(pdf_path, max_pages=10)
    assert page_count == 2
    assert "page one" in text
    assert "page two" in text

    # Test exceeding max pages limit
    with pytest.raises(ExtractionError, match="exceeds page limit"):
        extract_text_from_pdf(pdf_path, max_pages=1)


def test_unified_extract_document_txt():
    content = "Hello world, testing unified document extractor."
    result = extract_document(content.encode("utf-8"), filename="test.txt")
    assert result.format == "txt"
    assert result.word_count == 6
    assert "Hello world" in result.text
