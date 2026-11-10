"""Text normalization and offset-aware tokenization module.

Preserves exact character offsets for highlighting while normalizing tokens for matching.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Token:
    text: str
    norm: str
    start: int
    end: int


@dataclass(frozen=True)
class SentenceSpan:
    text: str
    start: int
    end: int


# Tokenizer regex: matches alphanumeric words, allowing internal apostrophes/hyphens
WORD_PATTERN = re.compile(r"\b[\w]+(?:['’\-][\w]+)*\b", re.UNICODE)

# Sentence boundary regex
SENTENCE_SPLIT_PATTERN = re.compile(
    r'(?<=[.!?])\s+(?=[A-Z0-9“"(\[])|\n{2,}', re.UNICODE
)


def normalize_string(text: str) -> str:
    """Standardize Unicode NFKC, strip leading/trailing whitespace."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return text


def tokenize_with_offsets(text: str) -> list[Token]:
    """Tokenize text into words while recording exact character start and end offsets.
    
    Returns list of Token(text, norm, start, end).
    """
    tokens: list[Token] = []
    for match in WORD_PATTERN.finditer(text):
        raw_word = match.group()
        norm_word = raw_word.lower()
        tokens.append(
            Token(
                text=raw_word,
                norm=norm_word,
                start=match.start(),
                end=match.end(),
            )
        )
    return tokens


def get_sentence_spans(text: str) -> list[SentenceSpan]:
    """Extract individual sentences with their start and end character offsets in original text."""
    spans: list[SentenceSpan] = []
    start = 0
    for match in SENTENCE_SPLIT_PATTERN.finditer(text):
        candidate = text[start:match.start()].strip()
        if candidate:
            # find precise non-whitespace boundaries within the slice
            actual_start = start + (len(text[start:match.start()]) - len(text[start:match.start()].lstrip()))
            actual_end = actual_start + len(candidate)
            spans.append(
                SentenceSpan(
                    text=candidate,
                    start=actual_start,
                    end=actual_end,
                )
            )
        start = match.end()

    # Trailing sentence
    remaining = text[start:].strip()
    if remaining:
        actual_start = start + (len(text[start:]) - len(text[start:].lstrip()))
        actual_end = actual_start + len(remaining)
        spans.append(
            SentenceSpan(
                text=remaining,
                start=actual_start,
                end=actual_end,
            )
        )

    return spans
