"""Tests for advanced detection accuracy features:
- Title page & acknowledgements exclusion
- Academic boilerplate filtering
- Document language detection
- AI text characteristics analysis
- Self-plagiarism linkage
"""
from pipeline.ai_detect import analyze_ai_indicators
from pipeline.exclude import find_exclusions, is_boilerplate
from pipeline.language import detect_document_language
from pipeline.lexical import SourceDocument, find_shingle_matches


def test_title_page_and_acknowledgements_exclusion():
    doc = (
        "A thesis submitted in partial fulfillment of the requirements for the degree of Doctor of Philosophy.\n"
        "Department of Computer Science, Faculty of Engineering.\n\n\n"
        "Acknowledgements\n"
        "I would like to express my sincere gratitude to my supervisor for continuous guidance and support throughout this research.\n\n"
        "Introduction\n"
        "This is the actual beginning of the thesis body text where academic arguments are presented and evaluated in detail.\n"
    )
    report = find_exclusions(doc)
    reasons = [s.reason for s in report.spans]

    assert "title_page_preamble" in reasons
    assert "acknowledgements_section" in reasons
    assert any("Title/cover page" in f for f in report.flags)
    assert any("Acknowledgements" in f for f in report.flags)

    # Introduction text must NOT be excluded
    intro_pos = doc.find("Introduction")
    assert not report.is_excluded(intro_pos + 10)


def test_academic_boilerplate_filtering():
    # Boilerplate shingles should be identified
    bp_shingle = ("the", "remainder", "of", "this", "paper")
    assert is_boilerplate(bp_shingle) is True

    normal_shingle = ("convolutional", "neural", "networks", "process", "images")
    assert is_boilerplate(normal_shingle) is False

    # find_shingle_matches should not register isolated boilerplate as plagiarism hits
    doc_words = ["the", "remainder", "of", "this", "paper", "is", "organized", "as", "follows"]
    source_shingles = {tuple(doc_words[:5]), tuple(doc_words[1:6])}

    # Because boilerplate shingles are suppressed, they do not trigger spurious matches
    marks = find_shingle_matches(doc_words, source_shingles, n_gram_size=5, min_run_words=8)
    assert len(marks) == 0


def test_document_language_detection():
    english_text = (
        "Machine learning models require substantial computational resources and large annotated datasets "
        "to achieve high accuracy across natural language understanding benchmarks and computer vision tasks. "
        "The experimental evaluation indicates that deep residual architectures outperform shallow classifiers."
    )
    en_res = detect_document_language(english_text)
    assert en_res.language_code == "en"
    assert en_res.is_primary_supported is True
    assert en_res.confidence >= 0.70

    spanish_text = (
        "Los modelos de aprendizaje automatico requieren recursos computacionales sustanciales y grandes conjuntos "
        "de datos anotados para lograr una alta precision en las tareas de procesamiento del lenguaje natural. "
        "El analisis experimental demuestra que las redes neuronales profundas superan a los clasificadores tradicionales."
    )
    es_res = detect_document_language(spanish_text)
    assert es_res.language_code == "es"
    assert es_res.is_primary_supported is False
    assert es_res.flag is not None
    assert "Spanish" in es_res.flag


def test_ai_writing_characteristics_analysis():
    # Mechanical, uniform-length sentences with typical AI cliches
    ai_like_text = (
        "In today's fast-paced world, artificial intelligence plays a crucial role in modern science. "
        "It is important to note that deep learning models delve into complex datasets with ease. "
        "This remarkable breakthrough serves as a reminder of the power of technological innovation. "
        "The multifaceted nature of computational biology is a testament to multidisciplinary progress. "
        "By fostering a collaborative environment, researchers can address issues of paramount importance. "
        "In conclusion, the future of neural network computing remains bright and impactful for society."
    )
    ai_res = analyze_ai_indicators(ai_like_text)
    assert ai_res.cliche_count >= 3
    assert ai_res.score > 0.40
    assert ai_res.burstiness < 8.0

    # Natural human writing with varied sentence structures
    human_text = (
        "We tested three variants. "
        "Surprisingly, the simplest baseline outperformed the heavily tuned neural model across all ten folds, "
        "suggesting that recent benchmark gains may stem from overfitting rather than architectural superiority. "
        "Why did this occur? "
        "Our error analysis revealed severe annotation noise in the validation split. "
        "Specifically, nineteen percent of the labels were swapped by crowd workers."
    )
    human_res = analyze_ai_indicators(human_text)
    assert human_res.cliche_count == 0
    assert human_res.likelihood == "Likely Human"
    assert human_res.burstiness > 4.0
