"""Candidate retrieval module combining local corpus search and cached web search.

Queries local inverted index and open web search, fetches candidate pages with
disk caching, and enforces partial-scan safety notifications.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from index.corpus import LocalCorpusIndex
from pipeline.chunk import extract_candidate_queries
from pipeline.lexical import SourceDocument
from pipeline.normalize import SentenceSpan, Token
from pipeline.sources import DEFAULT_CACHE_DIR, fetch_web_page


@dataclass
class RetrievalResult:
    sources: list[SourceDocument] = field(default_factory=list)
    searched_description: str = ""
    is_partial: bool = False
    partial_reason: str = ""
    candidate_urls: list[str] = field(default_factory=list)
    search_errors: int = 0
    fetch_errors: int = 0


def _get_query_cache_path(query: str, k: int, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(f"search:{query}:{k}".encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


def search_web_candidates(
    query: str,
    max_results: int = 5,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> tuple[list[str], str]:
    """Search DuckDuckGo for candidate URLs matching the query phrase.
    
    Returns (list_of_urls, error_message).
    """
    cache_file = _get_query_cache_path(query, max_results, cache_dir)
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            return cached.get("urls", []), cached.get("error", "")
        except Exception:
            pass

    urls: list[str] = []
    error = ""

    try:
        from duckduckgo_search import DDGS

        ddgs = DDGS()
        # 1. Try exact phrase search first
        exact_query = f'"{query}"'
        try:
            results = list(ddgs.text(exact_query, max_results=max_results))
            for r in results:
                u = r.get("href") or r.get("url")
                if u:
                    urls.append(u)
        except Exception:
            pass

        # 2. If exact yielded fewer than 2 results, try keyword search
        if len(urls) < 2:
            results = list(ddgs.text(query, max_results=max_results))
            for r in results:
                u = r.get("href") or r.get("url")
                if u and u not in urls:
                    urls.append(u)

    except Exception as e:
        error = str(e)[:120]

    cache_file.write_text(json.dumps({"urls": urls, "error": error}), encoding="utf-8")
    return urls, error


def normalize_url(url: str) -> str:
    """Normalize URL by stripping tracking parameters, fragments, and trailing slashes."""
    try:
        p = urlparse(url)
        norm_path = p.path.rstrip("/")
        return f"{p.scheme}://{p.netloc}{norm_path}"
    except Exception:
        return url


def retrieve_candidates(
    doc_text: str,
    tokens: list[Token],
    sentences: list[SentenceSpan] | None = None,
    local_corpus: LocalCorpusIndex | None = None,
    extra_sources: list[SourceDocument] | None = None,
    enable_web_search: bool = False,
    max_queries: int = 15,
    results_per_query: int = 4,
    max_pages_to_fetch: int = 30,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> RetrievalResult:
    """Retrieve candidate source documents for plagiarism comparison."""
    sources: list[SourceDocument] = []
    seen_labels: set[str] = set()

    # 1. Add extra provided source documents
    for src in extra_sources or []:
        if src.label not in seen_labels:
            sources.append(src)
            seen_labels.add(src.label)

    # 2. Local corpus candidate retrieval
    searched_parts: list[str] = []
    if extra_sources:
        searched_parts.append(f"{len(extra_sources)} provided files")

    if local_corpus and len(local_corpus) > 0:
        query_words = [t.norm for t in tokens if len(t.norm) > 3]
        corpus_matches = local_corpus.search_candidates(query_words, top_k=20, min_overlap=3)
        for doc in corpus_matches:
            if doc.label not in seen_labels:
                sources.append(doc)
                seen_labels.add(doc.label)
        searched_parts.append(f"local academic corpus ({len(local_corpus)} indexed documents)")

    # 3. Live Web Search (if enabled)
    candidate_urls: list[str] = []
    search_errors = 0
    fetch_errors = 0
    last_error = ""

    if enable_web_search:
        queries = extract_candidate_queries(
            doc_text, sentences=sentences, max_queries=max_queries, query_word_count=12
        )

        seen_urls: set[str] = set()
        for q in queries:
            urls, err = search_web_candidates(
                q, max_results=results_per_query, cache_dir=cache_dir
            )
            if err:
                search_errors += 1
                last_error = err
            for u in urls:
                norm_u = normalize_url(u)
                if norm_u not in seen_urls and norm_u not in seen_labels:
                    seen_urls.add(norm_u)
                    candidate_urls.append(u)

            # Polite crawl delay between distinct web queries
            time.sleep(0.5)

        # Fetch candidate web pages
        fetched_count = 0
        for u in candidate_urls[:max_pages_to_fetch]:
            page_text, fetch_err = fetch_web_page(u, cache_dir=cache_dir)
            if fetch_err:
                fetch_errors += 1
                last_error = fetch_err
            # Only include pages with substantial content (>= 50 words)
            if len(page_text.split()) >= 50:
                doc = SourceDocument.from_text(
                    source_id=len(sources) + 1,
                    label=u,
                    text=page_text,
                    kind="web",
                )
                sources.append(doc)
                seen_labels.add(u)
                fetched_count += 1

        searched_parts.append(f"open web search ({fetched_count} candidate pages fetched)")

    # 4. Partial Scan determination
    is_partial = False
    partial_reason = ""

    if enable_web_search and search_errors > 0:
        is_partial = True
        partial_reason = (
            f"{search_errors} web searches encountered network/rate limitations ({last_error}). "
            "Similarity score may be understated."
        )
    elif enable_web_search and fetch_errors > (max_pages_to_fetch // 2):
        is_partial = True
        partial_reason = (
            f"{fetch_errors} candidate web pages could not be retrieved. "
            "Similarity score may be understated."
        )
    elif not enable_web_search and not extra_sources and (not local_corpus or len(local_corpus) == 0):
        is_partial = True
        partial_reason = "No reference corpus, files, or web search were available to compare against."

    searched_description = " + ".join(searched_parts) if searched_parts else "none"

    return RetrievalResult(
        sources=sources,
        searched_description=searched_description,
        is_partial=is_partial,
        partial_reason=partial_reason,
        candidate_urls=candidate_urls,
        search_errors=search_errors,
        fetch_errors=fetch_errors,
    )
