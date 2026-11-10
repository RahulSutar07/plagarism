"""Document text extraction module.

Extracts text from PDF, DOCX, TXT, and raw strings. Enforces page limits
and zip-bomb protections, strips headers/footers, and returns extracted text with metadata.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


class ExtractionError(Exception):
    """Raised when extraction fails due to format errors or security limit violations."""
    pass


@dataclass
class ExtractionResult:
    text: str
    format: str
    page_count: int
    word_count: int
    char_count: int
    is_scanned_pdf: bool = False


def _strip_page_noise(text: str) -> str:
    """Strip common headers, footers, and solitary page numbers from extracted text."""
    lines = text.splitlines()
    cleaned_lines = []
    page_number_pattern = re.compile(
        r"^\s*(?:page\s+\d+(?:\s*(?:of|/)\s*\d+)?|\d+)\s*$", re.IGNORECASE
    )
    for line in lines:
        if page_number_pattern.match(line):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def extract_text_from_txt(content: bytes | str) -> str:
    """Extract text from plain text input."""
    if isinstance(content, str):
        return content
    for enc in ("utf-8", "utf-16", "latin-1", "cp1252"):
        try:
            return content.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="ignore")


def extract_text_from_docx(
    file_source: str | Path | BinaryIO | bytes,
    max_uncompressed_bytes: int = 150 * 1024 * 1024,
) -> str:
    """Extract text from DOCX document including paragraphs and tables.
    
    Includes zip-bomb protection with fallback to direct XML parsing.
    """
    if isinstance(file_source, (str, Path)):
        file_path = Path(file_source)
        if not file_path.exists():
            raise ExtractionError(f"File not found: {file_path}")
        bio = io.BytesIO(file_path.read_bytes())
    elif isinstance(file_source, bytes):
        bio = io.BytesIO(file_source)
    else:
        bio = io.BytesIO(file_source.read())

    # Zip-bomb protection: check uncompressed XML text size (excluding media/images)
    try:
        with zipfile.ZipFile(bio, "r") as zf:
            xml_size = sum(
                info.file_size for info in zf.infolist()
                if info.filename.endswith((".xml", ".rels"))
            )
            total_size = sum(info.file_size for info in zf.infolist())
            # Zip bombs typically expand XML by orders of magnitude
            if xml_size > 50 * 1024 * 1024 or total_size > max_uncompressed_bytes:
                raise ExtractionError(
                    f"Decompressed DOCX size ({total_size} bytes) exceeds safety limit ({max_uncompressed_bytes} bytes)."
                )
    except zipfile.BadZipFile as e:
        raise ExtractionError(f"Invalid or corrupted DOCX file: {e}") from e

    # Primary extraction: python-docx
    bio.seek(0)
    try:
        from docx import Document
        doc = Document(bio)
        parts: list[str] = []
        for p in doc.paragraphs:
            if p.text and p.text.strip():
                parts.append(p.text)

        for table in doc.tables:
            for row in table.rows:
                try:
                    row_text = " \t ".join(cell.text.strip() for cell in row.cells if cell.text and cell.text.strip())
                    if row_text:
                        parts.append(row_text)
                except Exception:
                    continue

        extracted = "\n\n".join(parts)
        if extracted.strip():
            return extracted
    except Exception:
        pass

    # Secondary fallback: Direct word/document.xml extraction
    try:
        bio.seek(0)
        with zipfile.ZipFile(bio, "r") as zf:
            if "word/document.xml" in zf.namelist():
                xml_raw = zf.read("word/document.xml").decode("utf-8", errors="ignore")
                matches = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml_raw)
                if matches:
                    return " ".join(matches)
    except Exception as e:
        raise ExtractionError(f"Failed to parse DOCX document: {e}") from e

    return ""


def extract_text_from_pdf(
    file_source: str | Path | BinaryIO | bytes,
    max_pages: int = 200,
) -> tuple[str, int]:
    """Extract text from PDF using PyMuPDF (fitz) with fallback to pypdf.
    
    Enforces maximum page limits.
    Returns (extracted_text, page_count).
    """
    raw_bytes: bytes
    if isinstance(file_source, (str, Path)):
        p = Path(file_source)
        if not p.exists():
            raise ExtractionError(f"File not found: {p}")
        raw_bytes = p.read_bytes()
    elif isinstance(file_source, bytes):
        raw_bytes = file_source
    else:
        raw_bytes = file_source.read()

    # Try PyMuPDF first
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
        page_count = len(doc)
        if page_count > max_pages:
            doc.close()
            raise ExtractionError(
                f"PDF exceeds page limit: {page_count} pages (maximum allowed is {max_pages})."
            )
        pages_text: list[str] = []
        for page in doc:
            t = page.get_text() or ""
            pages_text.append(_strip_page_noise(t))

        full_text = "\n\n".join(pages_text)
        # If little to no text was extracted, attempt OCR
        if len(full_text.split()) < 15 and page_count > 0:
            ocr_pages: list[str] = []
            for page in doc[:min(page_count, 10)]:
                try:
                    tp = page.get_textpage_ocr(flags=0, language="eng")
                    ocr_text = page.get_text(textpage=tp) or ""
                    if ocr_text.strip():
                        ocr_pages.append(_strip_page_noise(ocr_text))
                except Exception:
                    pass
            if ocr_pages:
                full_text = "\n\n".join(ocr_pages)

        doc.close()
        return full_text, page_count
    except ImportError:
        pass
    except ExtractionError:
        raise
    except Exception:
        # Fallback to pypdf if fitz had an unexpected parse issue
        pass

    # Fallback to pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw_bytes))
        page_count = len(reader.pages)
        if page_count > max_pages:
            raise ExtractionError(
                f"PDF exceeds page limit: {page_count} pages (maximum allowed is {max_pages})."
            )
        pages_text = []
        for page in reader.pages:
            t = page.extract_text() or ""
            pages_text.append(_strip_page_noise(t))
        return "\n\n".join(pages_text), page_count
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(f"Failed to parse PDF document: {e}") from e


def extract_document(
    file_source: str | Path | BinaryIO | bytes,
    filename: str | None = None,
    max_pages: int = 200,
    max_docx_uncompressed_bytes: int = 50 * 1024 * 1024,
) -> ExtractionResult:
    """Unified entry point to extract text from any supported document format."""
    ext = ""
    if filename:
        ext = Path(filename).suffix.lower()
    elif isinstance(file_source, (str, Path)):
        ext = Path(file_source).suffix.lower()

    text: str
    page_count: int = 1

    if ext == ".pdf":
        text, page_count = extract_text_from_pdf(file_source, max_pages=max_pages)
        fmt = "pdf"
    elif ext == ".docx":
        text = extract_text_from_docx(
            file_source, max_uncompressed_bytes=max_docx_uncompressed_bytes
        )
        fmt = "docx"
    elif ext == ".txt" or ext == "":
        if isinstance(file_source, (str, Path)):
            raw = Path(file_source).read_bytes()
        elif isinstance(file_source, bytes):
            raw = file_source
        else:
            raw = file_source.read()
        text = extract_text_from_txt(raw)
        fmt = "txt"
    else:
        raise ExtractionError(f"Unsupported file format '{ext}'. Allowed: .pdf, .docx, .txt")

    words = text.split()
    is_scanned = fmt == "pdf" and page_count > 0 and len(words) < 15
    return ExtractionResult(
        text=text,
        format=fmt,
        page_count=page_count,
        word_count=len(words),
        char_count=len(text),
        is_scanned_pdf=is_scanned,
    )
