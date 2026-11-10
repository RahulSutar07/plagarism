"""Combined scoring and detection coordinator module.

Coordinates anti-evasion, exclusion filtering, lexical shingling, and
semantic paraphrase detection into a comprehensive similarity score and match report.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pipeline.evasion import detect_and_clean_evasion
from pipeline.exclude import find_exclusions
from pipeline.lexical import (
    MatchSpan,
    SourceDocument,
    SourceMatchSummary,
    find_shingle_matches,
)
from pipeline.normalize import get_sentence_spans, tokenize_with_offsets
from pipeline.semantic import detect_paraphrase_pass


@dataclass
class CombinedAnalysisResult:
    cleaned_text: str
    total_words: int
    scored_words: int
    overall_similarity_pct: float
    exact_pct: float
    near_pct: float
    paraphrase_pct: float
    matched_words: int
    largest_single_source: str
    match_spans: list[MatchSpan] = field(default_factory=list)
    source_summaries: list[SourceMatchSummary] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    token_ownership: dict[int, tuple[int, Literal["exact", "near", "paraphrase"]]] = field(
        default_factory=dict
    )


def analyze_document(
    text: str,
    sources: list[SourceDocument],
    enable_paraphrase: bool = True,
    n_gram_size: int = 5,
    min_run_words: int = 8,
    min_cosine_threshold: float = 0.85,
    min_jaccard_threshold: float = 0.20,
) -> CombinedAnalysisResult:
    """Run full plagiarism analysis: evasion -> exclusions -> lexical -> semantic -> score."""
    # 1. Anti-evasion
    evasion_res = detect_and_clean_evasion(text)
    clean_txt = evasion_res.cleaned_text

    # 2. Exclusions & Citations
    excl_report = find_exclusions(clean_txt)

    # 3. Tokenize with character offsets
    tokens = tokenize_with_offsets(clean_txt)
    total_words = len(tokens)

    if total_words == 0 or not sources:
        return CombinedAnalysisResult(
            cleaned_text=clean_txt,
            total_words=total_words,
            scored_words=0,
            overall_similarity_pct=0.0,
            exact_pct=0.0,
            near_pct=0.0,
            paraphrase_pct=0.0,
            matched_words=0,
            largest_single_source="none",
            flags=evasion_res.flags + excl_report.flags,
        )

    # Scorable token mask
    scorable_indices = [
        idx for idx, t in enumerate(tokens) if not excl_report.is_excluded(t.start)
    ]
    scored_words = len(scorable_indices)
    if scored_words == 0:
        return CombinedAnalysisResult(
            cleaned_text=clean_txt,
            total_words=total_words,
            scored_words=0,
            overall_similarity_pct=0.0,
            exact_pct=0.0,
            near_pct=0.0,
            paraphrase_pct=0.0,
            matched_words=0,
            largest_single_source="none",
            flags=evasion_res.flags + excl_report.flags,
        )

    doc_words = [t.norm for t in tokens]
    scorable_set = set(scorable_indices)

    # 4. Lexical matching (exact & near)
    source_marks: dict[int, dict[int, Literal["exact", "near"]]] = {}
    for src in sources:
        source_marks[src.source_id] = find_shingle_matches(
            doc_words, src.shingles, n_gram_size=n_gram_size, min_run_words=min_run_words
        )

    # Resolve token ownership for lexical hits
    sorted_sources = sorted(
        sources, key=lambda s: len(source_marks.get(s.source_id, {})), reverse=True
    )
    token_ownership: dict[int, tuple[int, Literal["exact", "near", "paraphrase"]]] = {}

    for src in sorted_sources:
        for token_idx, m_type in source_marks[src.source_id].items():
            if token_idx in scorable_set and token_idx not in token_ownership:
                token_ownership[token_idx] = (src.source_id, m_type)

    # 5. Semantic / Paraphrase pass (Phase 3)
    sentences = get_sentence_spans(clean_txt)
    if enable_paraphrase and sources:
        detect_paraphrase_pass(
            text=clean_txt,
            tokens=tokens,
            sources=sources,
            token_ownership=token_ownership,
            is_excluded_fn=excl_report.is_excluded,
            sentences=sentences,
            min_cosine_threshold=min_cosine_threshold,
            min_jaccard_threshold=min_jaccard_threshold,
        )

    # 6. Build unified MatchSpans
    match_spans: list[MatchSpan] = []
    i = 0
    while i < total_words:
        if i in token_ownership:
            sid, mtype = token_ownership[i]
            j = i
            while (
                j + 1 < total_words
                and (j + 1) in token_ownership
                and token_ownership[j + 1] == (sid, mtype)
            ):
                j += 1

            match_spans.append(
                MatchSpan(
                    start_token_idx=i,
                    end_token_idx=j + 1,
                    start_char=tokens[i].start,
                    end_char=tokens[j].end,
                    source_id=sid,
                    match_type=mtype,  # type: ignore[arg-type]
                    matched_word_count=(j - i + 1),
                )
            )
            i = j + 1
        else:
            i += 1

    # 7. Compute breakdown metrics
    counts = {"exact": 0, "near": 0, "paraphrase": 0}
    per_source_counts: dict[int, int] = {}

    for token_idx, (sid, mtype) in token_ownership.items():
        if token_idx in scorable_set:
            counts[mtype] = counts.get(mtype, 0) + 1
            per_source_counts[sid] = per_source_counts.get(sid, 0) + 1

    matched_words = sum(counts.values())
    overall_pct = (matched_words / float(scored_words)) * 100.0 if scored_words else 0.0
    exact_pct = (counts["exact"] / float(scored_words)) * 100.0 if scored_words else 0.0
    near_pct = (counts["near"] / float(scored_words)) * 100.0 if scored_words else 0.0
    paraphrase_pct = (counts["paraphrase"] / float(scored_words)) * 100.0 if scored_words else 0.0

    # 8. Source summaries
    source_summaries: list[SourceMatchSummary] = []
    sources_by_id = {s.source_id: s for s in sources}

    for sid, count in sorted(per_source_counts.items(), key=lambda x: x[1], reverse=True):
        src = sources_by_id[sid]
        pct = (count / float(scored_words)) * 100.0

        matching_indices = sorted(
            idx for idx, (owner_sid, _) in token_ownership.items() if owner_sid == sid and idx in scorable_set
        )
        longest_run = 0
        curr_run = 0
        prev_idx = -2
        for idx in matching_indices:
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
                source_id=sid,
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

    return CombinedAnalysisResult(
        cleaned_text=clean_txt,
        total_words=total_words,
        scored_words=scored_words,
        overall_similarity_pct=round(overall_pct, 1),
        exact_pct=round(exact_pct, 1),
        near_pct=round(near_pct, 1),
        paraphrase_pct=round(paraphrase_pct, 1),
        matched_words=matched_words,
        largest_single_source=largest_str,
        match_spans=match_spans,
        source_summaries=source_summaries,
        flags=evasion_res.flags + excl_report.flags,
        token_ownership=token_ownership,
    )
