from index.corpus import LocalCorpusIndex


def test_corpus_index_add_and_search():
    index = LocalCorpusIndex(n_gram_size=5)

    doc1 = index.add_document(
        doc_id=1,
        title="Deep Learning in Computer Vision",
        text="Convolutional neural networks represent a specialized category of deep artificial neural networks.",
        kind="corpus",
    )
    index.add_document(
        doc_id=2,
        title="Macroeconomic Policy",
        text="Central monetary authorities utilize benchmark interest rates and open market operations.",
        kind="corpus",
    )

    assert len(index) == 2
    assert doc1.source_id == 1

    # Search for vision concepts
    query_words = ["convolutional", "neural", "networks", "vision", "deep"]
    matches = index.search_candidates(query_words, top_k=5, min_overlap=2)

    assert len(matches) >= 1
    assert matches[0].source_id == 1


def test_corpus_index_load_json(tmp_path):
    import json

    data = {
        "documents": [
            {
                "id": 101,
                "title": "Quantum Algorithms",
                "text": "Superconducting qubits maintain quantum coherence to execute algorithms.",
            },
            {
                "id": 102,
                "title": "CRISPR Therapeutics",
                "text": "The Cas9 enzyme introduces double-strand breaks at targeted locations.",
            },
        ]
    }
    json_file = tmp_path / "corpus.json"
    json_file.write_text(json.dumps(data), encoding="utf-8")

    index = LocalCorpusIndex()
    count = index.load_from_json(json_file)

    assert count == 2
    assert len(index) == 2
    all_docs = index.get_all_documents()
    assert any(d.source_id == 101 for d in all_docs)
