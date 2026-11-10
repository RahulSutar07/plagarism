"""Web page fetcher with disk caching and robots.txt compliance.

Fetches and extracts clean body text from web URLs and PDFs, stripping
navigation menus, headers, footers, and advertisements via trafilatura.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from pipeline.evasion import ZERO_WIDTH_CHARS

DEFAULT_CACHE_DIR = Path(".pc_cache")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 (PlagiarismPreCheck; student research tool)"
REQUEST_HEADERS = {"User-Agent": USER_AGENT}

_robots_cache: dict[str, RobotFileParser] = {}


def _get_cache_path(key: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    """Generate SHA-1 cache file path."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


def is_robots_allowed(url: str, user_agent: str = USER_AGENT) -> bool:
    """Verify site robots.txt permits crawling the target URL."""
    try:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in _robots_cache:
            rp = RobotFileParser()
            robots_url = f"{base}/robots.txt"
            try:
                r = requests.get(robots_url, timeout=5, headers=REQUEST_HEADERS)
                lines = r.text.splitlines() if r.status_code == 200 else []
                rp.parse(lines)
            except Exception:
                rp.parse([])
            rp.modified()
            _robots_cache[base] = rp

        return _robots_cache[base].can_fetch(user_agent, url)
    except Exception:
        # Default to allowing if robots.txt cannot be resolved
        return True


def fetch_web_page(
    url: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    timeout_s: int = 10,
    max_pdf_bytes: int = 8 * 1024 * 1024,
    max_pdf_pages: int = 80,
) -> tuple[str, str]:
    """Fetch URL and extract clean text. Returns (cleaned_text, error_message).
    
    Uses disk caching to prevent duplicate web requests.
    """
    cache_file = _get_cache_path(f"page:{url}", cache_dir)
    if cache_file.exists():
        try:
            cached_data = json.loads(cache_file.read_text(encoding="utf-8"))
            return cached_data.get("text", ""), cached_data.get("error", "")
        except Exception:
            pass

    # Check robots.txt
    if not is_robots_allowed(url):
        result = ("", "Disallowed by site robots.txt")
        cache_file.write_text(json.dumps({"text": "", "error": result[1]}), encoding="utf-8")
        return result

    try:
        r = requests.get(url, timeout=timeout_s, headers=REQUEST_HEADERS)
        r.raise_for_status()

        content_type = r.headers.get("content-type", "").lower()
        text = ""

        # Handle PDF responses
        if "pdf" in content_type or url.lower().endswith(".pdf"):
            if len(r.content) > max_pdf_bytes:
                return ("", f"PDF exceeds maximum download limit ({max_pdf_bytes} bytes)")

            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(r.content))
            pages = reader.pages[:max_pdf_pages]
            text = "\n\n".join((p.extract_text() or "") for p in pages)
        else:
            # Handle HTML responses via trafilatura for clean text extraction
            try:
                import trafilatura
                extracted = trafilatura.extract(
                    r.text,
                    include_links=False,
                    include_images=False,
                    include_tables=True,
                )
                text = extracted or ""
            except Exception:
                # Fallback simple tag stripper
                text = re.sub(r"<[^>]+>", " ", r.text)

        # Clean text
        text = text.translate(ZERO_WIDTH_CHARS)[:300_000]
        cache_file.write_text(json.dumps({"text": text, "error": ""}), encoding="utf-8")
        return (text, "")

    except Exception as e:
        err_msg = str(e)[:120]
        cache_file.write_text(json.dumps({"text": "", "error": err_msg}), encoding="utf-8")
        return ("", err_msg)
