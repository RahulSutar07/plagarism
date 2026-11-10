from pipeline.chunk import create_sentence_windows, extract_candidate_queries
from pipeline.normalize import get_sentence_spans


def test_sentence_windows_sliding():
    text = (
        "This is the first sentence. This is the second sentence. "
        "This is the third sentence. This is the fourth sentence. "
        "This is the fifth sentence."
    )
    sentences = get_sentence_spans(text)
    assert len(sentences) == 5

    windows = create_sentence_windows(sentences, window_size=3, stride=1)
    # 5 sentences with window_size=3 and stride=1 yields 5 - 3 + 1 = 3 windows
    assert len(windows) == 3
    assert windows[0].sentence_count == 3
    assert "first sentence" in windows[0].text
    assert "third sentence" in windows[0].text
    assert "second sentence" in windows[1].text
    assert "fourth sentence" in windows[1].text


def test_extract_candidate_queries_limits_and_spacing():
    # Construct 10 sentences with 15 words each
    sentences_text = " ".join(
        f"This is sentence number {i} containing enough descriptive vocabulary words to test query extraction properly."
        for i in range(10)
    )
    sentences = get_sentence_spans(sentences_text)
    queries = extract_candidate_queries(sentences_text, sentences=sentences, max_queries=4)
    assert len(queries) == 4
    for q in queries:
        assert len(q.split()) >= 8
