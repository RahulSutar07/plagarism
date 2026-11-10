import json

from index.corpus import LocalCorpusIndex
from pipeline.normalize import tokenize_with_offsets
from pipeline.retrieve import normalize_url, retrieve_candidates
from pipeline.sources import fetch_web_page


def test_normalize_url():
    url1 = "https://example.com/research/paper/"
    assert normalize_url(url1) == "https://example.com/research/paper"

    url2 = "http://arxiv.org/abs/2103.00020?ref=rss#sec2"
    assert normalize_url(url2) == "http://arxiv.org/abs/2103.00020"


def test_fetch_web_page_uses_cache(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    # Pre-populate cache
    import hashlib

    url = "https://example.org/sample-paper"
    key = f"page:{url}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    cache_file = cache_dir / f"{digest}.json"
    cached_content = {
        "text": "This is cached academic research content extracted from example.org.",
        "error": "",
    }
    cache_file.write_text(json.dumps(cached_content), encoding="utf-8")

    text, err = fetch_web_page(url, cache_dir=cache_dir)
    assert "cached academic research" in text
    assert err == ""


def test_retrieve_candidates_local_and_partial_flags():
    index = LocalCorpusIndex()
    index.add_document(
        doc_id=1,
        title="Attention Mechanisms",
        text="Transformers rely on multi-head self-attention mechanisms to map sequence dependencies.",
    )

    doc_text = (
        "Modern deep learning architectures utilize self-attention mechanisms "
        "and transformers across computational linguistic domains."
    )
    tokens = tokenize_with_offsets(doc_text)

    # 1. Retrieve with local corpus only (offline)
    res = retrieve_candidates(
        doc_text=doc_text,
        tokens=tokens,
        local_corpus=index,
        enable_web_search=False,
    )
    assert len(res.sources) == 1
    assert res.sources[0].label == "Attention Mechanisms"
    assert res.is_partial is False
    assert "local academic corpus" in res.searched_description

    # 2. Retrieve with no sources available (should trigger partial scan flag)
    empty_res = retrieve_candidates(
        doc_text=doc_text,
        tokens=tokens,
        local_corpus=None,
        extra_sources=None,
        enable_web_search=False,
    )
    assert len(empty_res.sources) == 0
    assert empty_res.is_partial is True
    assert "No reference corpus" in empty_res.partial_reason
