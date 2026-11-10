"""Exact and near-lexical matching engine using word shingling.

Implements N-gram shingling (N=5..8), contiguous run grouping, near-match bridging (gaps <= 3),
and passage offset mapping for visual highlighting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from pipeline.exclude import is_boilerplate
from pipeline.normalize import Token, tokenize_with_offsets

MatchType = Literal["exact", "near"]


@dataclass
class SourceDocument:
    source_id: int
    label: str
    kind: str  # "file" | "web" | "corpus"
    text: str
    words: list[str] = field(default_factory=list)
    shingles: set[tuple[str, ...]] = field(default_factory=set)

    @classmethod
    def from_text(
        cls,
        source_id: int,
        label: str,
        text: str,
        kind: str = "file",
        n_gram_size: int = 5,
    ) -> SourceDocument:
        tokens = tokenize_with_offsets(text)
        words = [t.norm for t in tokens]
        shingles: set[tuple[str, ...]] = set()
        if len(words) >= n_gram_size:
            for i in range(len(words) - n_gram_size + 1):
                shingles.add(tuple(words[i : i + n_gram_size]))
        return cls(
            source_id=source_id,
            label=label,
            kind=kind,
            text=text,
            words=words,
            shingles=shingles,
        )


@dataclass
class MatchSpan:
    start_token_idx: int
    end_token_idx: int
    start_char: int
    end_char: int
    source_id: int
    match_type: MatchType
    matched_word_count: int


@dataclass
class SourceMatchSummary:
    source_id: int
    label: str
    kind: str
    matched_words: int
    percentage: float
    confidence: Literal["high", "medium", "low"]
    longest_contiguous_run: int


@dataclass
class LexicalMatchResult:
    overall_similarity_pct: float
    exact_pct: float
    near_pct: float
    matched_word_count: int
    total_scored_words: int
    token_ownership: dict[int, tuple[int, MatchType]]  # token_idx -> (source_id, match_type)
    match_spans: list[MatchSpan]
    source_summaries: list[SourceMatchSummary]
    largest_single_source_summary: str


def find_shingle_matches(
    doc_words: list[str],
    source_shingles: set[tuple[str, ...]],
    n_gram_size: int = 5,
    min_run_words: int = 8,
) -> dict[int, MatchType]:
    """Identify matching word token indices against a source's shingle set.
    
    Consecutive hits >= min_run_words are marked 'exact'.
    Intervening gaps <= 3 words between valid runs are marked 'near'.
    """
    word_count = len(doc_words)
    if word_count < n_gram_size:
        return {}

    n = word_count - n_gram_size + 1
    hit = []
    for i in range(n):
        shingle = tuple(doc_words[i : i + n_gram_size])
        if is_boilerplate(shingle):
            hit.append(False)
        else:
            hit.append(shingle in source_shingles)

    # Group contiguous hits into candidate runs
    runs: list[tuple[int, int]] = []
    i = 0
    while i < len(hit):
        if hit[i]:
            j = i
            while j < len(hit) and hit[j]:
                j += 1
            # Run covers tokens from i to j - 1 + n_gram_size (exclusive boundary)
            runs.append((i, j - 1 + n_gram_size))
            i = j
        else:
            i += 1

    # Filter out runs shorter than minimum threshold
    valid_runs = [(start, end) for start, end in runs if (end - start) >= min_run_words]
    if not valid_runs:
        return {}

    marks: dict[int, MatchType] = {}
    for start, end in valid_runs:
        for idx in range(start, end):
            marks[idx] = "exact"

    # Bridge small gaps (<= 3 words) between adjacent valid runs as 'near' matches
    for (start1, end1), (start2, end2) in zip(valid_runs, valid_runs[1:]):
        gap = start2 - end1
        if 0 < gap <= 3:
            for idx in range(end1, start2):
                marks[idx] = "near"

    return marks


def match_document_lexical(
    tokens: list[Token],
    sources: list[SourceDocument],
    is_excluded_fn: Callable[[int], bool] | None = None,
    n_gram_size: int = 5,
    min_run_words: int = 8,
) -> LexicalMatchResult:
    """Perform exact and near lexical matching of document tokens against reference sources."""
    total_tokens = len(tokens)
    if total_tokens == 0 or not sources:
        return LexicalMatchResult(
            overall_similarity_pct=0.0,
            exact_pct=0.0,
            near_pct=0.0,
            matched_word_count=0,
            total_scored_words=0,
            token_ownership={},
            match_spans=[],
            source_summaries=[],
            largest_single_source_summary="none",
        )

    doc_words = [t.norm for t in tokens]

    # Mask scorable tokens (skip tokens that fall inside excluded regions)
    scorable_token_indices = [
        idx
        for idx, t in enumerate(tokens)
        if not (is_excluded_fn and is_excluded_fn(t.start))
    ]
    total_scored_words = len(scorable_token_indices)
    if total_scored_words == 0:
        return LexicalMatchResult(
            overall_similarity_pct=0.0,
            exact_pct=0.0,
            near_pct=0.0,
            matched_word_count=0,
            total_scored_words=0,
            token_ownership={},
            match_spans=[],
            source_summaries=[],
            largest_single_source_summary="none",
        )

    # 1. Compute matches for each source
    source_marks: dict[int, dict[int, MatchType]] = {}
    for src in sources:
        marks = find_shingle_matches(
            doc_words,
            src.shingles,
            n_gram_size=n_gram_size,
            min_run_words=min_run_words,
        )
        source_marks[src.source_id] = marks

    # 2. Resolve token ownership (prioritize sources with larger total match coverage)
    sorted_sources = sorted(
        sources,
        key=lambda s: len(source_marks.get(s.source_id, {})),
        reverse=True,
    )

    scorable_set = set(scorable_token_indices)
    token_ownership: dict[int, tuple[int, MatchType]] = {}

    for src in sorted_sources:
        marks = source_marks[src.source_id]
        for token_idx, match_type in marks.items():
            if token_idx in scorable_set and token_idx not in token_ownership:
                token_ownership[token_idx] = (src.source_id, match_type)

    # 3. Assemble continuous visual highlight MatchSpans
    match_spans: list[MatchSpan] = []
    i = 0
    while i < total_tokens:
        if i in token_ownership:
            src_id, m_type = token_ownership[i]
            j = i
            # Extend contiguous run as long as owner and match type are identical
            while (
                j + 1 < total_tokens
                and (j + 1) in token_ownership
                and token_ownership[j + 1] == (src_id, m_type)
            ):
                j += 1

            match_spans.append(
                MatchSpan(
                    start_token_idx=i,
                    end_token_idx=j + 1,
                    start_char=tokens[i].start,
                    end_char=tokens[j].end,
                    source_id=src_id,
                    match_type=m_type,
                    matched_word_count=(j - i + 1),
                )
            )
            i = j + 1
        else:
            i += 1

    # 4. Count breakdown
    type_counts: dict[MatchType, int] = {"exact": 0, "near": 0}
    per_source_counts: dict[int, int] = {}
    for token_idx, (src_id, m_type) in token_ownership.items():
        type_counts[m_type] = type_counts.get(m_type, 0) + 1
        per_source_counts[src_id] = per_source_counts.get(src_id, 0) + 1

    total_matched = sum(type_counts.values())

    # 5. Build per-source summaries
    source_summaries: list[SourceMatchSummary] = []
    sources_by_id = {s.source_id: s for s in sources}

    for src_id, count in sorted(per_source_counts.items(), key=lambda x: x[1], reverse=True):
        src = sources_by_id[src_id]
        pct = (count / float(total_scored_words)) * 100.0

        # Calculate longest contiguous run
        matching_token_indices = sorted(
            idx for idx, (sid, _) in token_ownership.items() if sid == src_id
        )
        longest_run = 0
        curr_run = 0
        prev_idx = -2
        for idx in matching_token_indices:
            if idx == prev_idx + 1:
                curr_run += 1
            else:
                curr_run = 1
            longest_run = max(longest_run, curr_run)
            prev_idx = idx

        confidence: Literal["high", "medium", "low"]
        if longest_run >= 20:
            confidence = "high"
        elif longest_run >= min_run_words:
            confidence = "medium"
        else:
            confidence = "low"

        source_summaries.append(
            SourceMatchSummary(
                source_id=src_id,
                label=src.label,
                kind=src.kind,
                matched_words=count,
                percentage=round(pct, 1),
                confidence=confidence,
                longest_contiguous_run=longest_run,
            )
        )

    largest_str = (
        f"{source_summaries[0].percentage:.1f}% ({source_summaries[0].label})"
        if source_summaries
        else "none"
    )

    overall_pct = (total_matched / float(total_scored_words)) * 100.0 if total_scored_words else 0.0
    exact_pct = (type_counts["exact"] / float(total_scored_words)) * 100.0 if total_scored_words else 0.0
    near_pct = (type_counts["near"] / float(total_scored_words)) * 100.0 if total_scored_words else 0.0

    return LexicalMatchResult(
        overall_similarity_pct=round(overall_pct, 1),
        exact_pct=round(exact_pct, 1),
        near_pct=round(near_pct, 1),
        matched_word_count=total_matched,
        total_scored_words=total_scored_words,
        token_ownership=token_ownership,
        match_spans=match_spans,
        source_summaries=source_summaries,
        largest_single_source_summary=largest_str,
    )
