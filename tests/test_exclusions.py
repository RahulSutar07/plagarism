from pipeline.exclude import find_exclusions


def test_references_section_excluded():
    body = (
        "Introduction to artificial intelligence and its impact on computational models. " * 10
    )
    references = (
        "\n\nReferences:\n1. Turing, A. M. (1950). Computing Machinery and Intelligence.\n"
        "2. Russell, S., & Norvig, P. (2020). Artificial Intelligence: A Modern Approach."
    )
    full_text = body + references

    report = find_exclusions(full_text)
    assert len(report.spans) >= 1
    ref_span = [s for s in report.spans if s.reason == "references_section"][0]
    assert ref_span.start >= len(body)
    assert report.is_excluded(len(full_text) - 10) is True
    assert report.is_excluded(10) is False


def test_quoted_and_cited_passages_excluded():
    quote_cited = (
        'The author states that "machine learning algorithms require significant training datasets '
        'to achieve high predictive generalization" (Smith et al., 2021).'
    )
    full_text = "Background context. " * 8 + quote_cited + " Conclusion context. " * 8

    report = find_exclusions(full_text)
    cited_spans = [s for s in report.spans if s.reason == "quoted_and_cited"]
    assert len(cited_spans) == 1
    assert "machine learning algorithms" in full_text[cited_spans[0].start : cited_spans[0].end]


def test_quoted_uncited_passages_not_excluded_and_flagged():
    quote_uncited = (
        'The author argues that "unsupervised pretraining enables language representations '
        'to capture complex hierarchical syntax structures without manual human labeling" and moves on.'
    )
    full_text = "Some opening academic sentences. " * 8 + quote_uncited + " Follow-up remarks. " * 8

    report = find_exclusions(full_text)
    # Quoted uncited should not be in excluded spans
    cited_spans = [s for s in report.spans if s.reason == "quoted_and_cited"]
    assert len(cited_spans) == 0
    assert report.quoted_uncited_count >= 1
    assert any("lacked nearby formal citations" in f for f in report.flags)
