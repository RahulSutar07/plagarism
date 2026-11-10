from pipeline.lexical import (
    SourceDocument,
    find_shingle_matches,
    match_document_lexical,
)
from pipeline.normalize import tokenize_with_offsets


def test_find_shingle_matches_exact_run():
    # Target document words
    doc_words = "the quick brown fox jumps over the lazy dog in the sunny park".split()
    # Source words matching 9 contiguous words (>= min_run of 8)
    source_text = "there was a moment when the quick brown fox jumps over the lazy dog in the meadow"
    source = SourceDocument.from_text(source_id=1, label="source1.txt", text=source_text, n_gram_size=5)

    matches = find_shingle_matches(doc_words, source.shingles, n_gram_size=5, min_run_words=8)
    assert len(matches) >= 9
    for idx, match_type in matches.items():
        assert match_type == "exact"


def test_ignore_matches_below_min_run():
    # Only 5 words match (below min_run_words = 8)
    doc_words = "computational algorithms process input arrays efficiently and quickly".split()
    source_text = "standard computational algorithms process input arrays with high complexity"
    source = SourceDocument.from_text(source_id=1, label="source1.txt", text=source_text, n_gram_size=5)

    matches = find_shingle_matches(doc_words, source.shingles, n_gram_size=5, min_run_words=8)
    assert len(matches) == 0


def test_near_matches_bridge_small_gaps():
    # Run 1 (8 words) + 2 filler words + Run 2 (8 words)
    run1 = "deep neural networks have demonstrated state of the art results"
    gap = "very remarkably"
    run2 = "across a wide range of computer vision benchmark datasets"
    doc_text = f"{run1} {gap} {run2}"

    source_text = f"{run1} and also {run2}"
    source = SourceDocument.from_text(source_id=1, label="source_ai.txt", text=source_text, n_gram_size=5)

    tokens = tokenize_with_offsets(doc_text)
    result = match_document_lexical(tokens, [source], min_run_words=8)

    assert result.overall_similarity_pct > 80.0
    assert result.exact_pct > 70.0
    assert result.near_pct > 0.0  # Gap should be bridged as near match
    assert len(result.match_spans) >= 1
    assert result.source_summaries[0].confidence == "high"


def test_exclusions_mask_in_lexical_match():
    copied = "artificial intelligence models require vast computational resources to converge"
    doc_text = f"Introductory remarks. {copied} Concluding remarks."
    source = SourceDocument.from_text(source_id=1, label="source.txt", text=copied, n_gram_size=5)
    tokens = tokenize_with_offsets(doc_text)

    # Exclude all tokens
    result_excluded = match_document_lexical(
        tokens, [source], is_excluded_fn=lambda char_offset: True
    )
    assert result_excluded.overall_similarity_pct == 0.0
    assert result_excluded.matched_word_count == 0


def test_match_determinism():
    text = (
        "Natural language processing provides techniques for analyzing textual documents "
        "and detecting semantic similarities across academic publications and student essays."
    )
    source = SourceDocument.from_text(source_id=1, label="nlp.txt", text=text, n_gram_size=5)
    tokens = tokenize_with_offsets(text)

    res1 = match_document_lexical(tokens, [source], min_run_words=8)
    res2 = match_document_lexical(tokens, [source], min_run_words=8)

    assert res1.overall_similarity_pct == res2.overall_similarity_pct
    assert res1.exact_pct == res2.exact_pct
    assert res1.token_ownership == res2.token_ownership
