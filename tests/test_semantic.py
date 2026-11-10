from pipeline.lexical import SourceDocument
from pipeline.score import analyze_document
from pipeline.semantic import compute_content_jaccard, detect_paraphrase_pass
from pipeline.normalize import tokenize_with_offsets


def test_content_jaccard_stopwords_filtered():
    # Sentences with identical stopwords but different content words
    s1 = "This is the time and the place for it."
    s2 = "That was a time or a place of that."
    j = compute_content_jaccard(s1, s2)
    assert j > 0.4  # "time", "place" overlap

    # Completely different content words
    s3 = "Quantum entanglement operates at millikelvin cryogenic states."
    s4 = "Central banking monetary systems fluctuate across global capital markets."
    j2 = compute_content_jaccard(s3, s4)
    assert j2 == 0.0


def test_paraphrase_detection_catches_rephrased_text():
    # Source text
    source_text = (
        "Convolutional neural networks represent a specialized category of deep artificial neural networks "
        "designed primarily for processing structured grid data such as digital images."
    )
    source = SourceDocument.from_text(source_id=1, label="source_cnn.txt", text=source_text)

    # Rephrased document text (scores 0% on 5-gram exact shingles)
    paraphrase_text = (
        "Convolutional neural architectures constitute a specialized class of deep networks "
        "engineered specifically to analyze visual grid arrays including digital imagery."
    )
    tokens = tokenize_with_offsets(paraphrase_text)
    token_ownership = {}

    res = detect_paraphrase_pass(
        text=paraphrase_text,
        tokens=tokens,
        sources=[source],
        token_ownership=token_ownership,
        min_cosine_threshold=0.75,
        min_jaccard_threshold=0.15,
    )

    assert len(res.detected_paraphrases) >= 1
    assert res.detected_paraphrases[0].source_id == 1
    assert res.paraphrase_word_count >= 8
    assert any(kind == "paraphrase" for _, kind in token_ownership.values())


def test_analyze_document_combined_pipeline():
    source_text = (
        "Convolutional neural networks represent a specialized category of deep artificial neural networks "
        "designed primarily for processing structured grid data such as digital images."
    )
    source = SourceDocument.from_text(source_id=1, label="cnn_source.txt", text=source_text)

    doc_text = (
        "Introductory notes. "
        "Convolutional neural networks represent a specialized category of deep artificial neural networks "
        "designed primarily for processing structured grid data such as digital images. "
        "Concluding notes."
    )

    result = analyze_document(doc_text, sources=[source], enable_paraphrase=True)
    assert result.overall_similarity_pct > 60.0
    assert result.exact_pct > 60.0
    assert result.total_words > 20
    assert len(result.source_summaries) >= 1
    assert result.source_summaries[0].label == "cnn_source.txt"
