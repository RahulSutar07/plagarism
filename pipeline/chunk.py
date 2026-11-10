"""Document chunking and sliding window module.

Implements sentence sliding windows (3 sentences, stride 1) with character offsets,
and representative query generation for candidate retrieval.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pipeline.normalize import SentenceSpan, get_sentence_spans


@dataclass(frozen=True)
class SentenceWindow:
    index: int
    text: str
    start: int
    end: int
    sentence_count: int


def create_sentence_windows(
    sentences: list[SentenceSpan],
    window_size: int = 3,
    stride: int = 1,
) -> list[SentenceWindow]:
    """Create sliding sentence windows with start/end character offsets."""
    if not sentences:
        return []

    windows: list[SentenceWindow] = []
    n = len(sentences)

    if n <= window_size:
        # Fewer sentences than window size: single window
        full_text = " ".join(s.text for s in sentences)
        return [
            SentenceWindow(
                index=0,
                text=full_text,
                start=sentences[0].start,
                end=sentences[-1].end,
                sentence_count=n,
            )
        ]

    for i in range(0, n - window_size + 1, stride):
        win_sents = sentences[i : i + window_size]
        win_text = " ".join(s.text for s in win_sents)
        windows.append(
            SentenceWindow(
                index=len(windows),
                text=win_text,
                start=win_sents[0].start,
                end=win_sents[-1].end,
                sentence_count=len(win_sents),
            )
        )

    return windows


def extract_candidate_queries(
    text: str,
    sentences: list[SentenceSpan] | None = None,
    is_excluded_fn: Callable[[int], bool] | None = None,
    max_queries: int = 25,
    query_word_count: int = 12,
) -> list[str]:
    """Extract representative search phrases from evenly distributed unexcluded sentences.
    
    Used to query candidate sources on the web or in reference databases.
    """
    if sentences is None:
        sentences = get_sentence_spans(text)

    candidates: list[str] = []
    for s in sentences:
        if is_excluded_fn and is_excluded_fn(s.start):
            continue

        words = s.text.split()
        # Only select sentences that are long enough (14-60 words) to yield distinctive phrases
        if 14 <= len(words) <= 60:
            phrase = " ".join(words[:query_word_count]).strip(" \"'“”()[].,;:")
            if len(phrase.split()) >= min(8, query_word_count):
                candidates.append(phrase)

    if not candidates:
        # Fallback to any unexcluded sentence if strict length yields nothing
        for s in sentences:
            if is_excluded_fn and is_excluded_fn(s.start):
                continue
            words = s.text.split()
            if len(words) >= 6:
                candidates.append(" ".join(words[:query_word_count]).strip(" \"'“”()[].,;:"))

    if not candidates:
        return []

    if len(candidates) <= max_queries:
        return candidates

    # Evenly pick queries across the document
    step = len(candidates) / float(max_queries)
    selected_queries = [candidates[int(i * step)] for i in range(max_queries)]
    return selected_queries
