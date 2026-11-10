"""Local reference corpus manager and indexer.

Stores and indexes reference documents (Wikipedia, arXiv, OpenAlex, academic datasets)
on the worker disk, enabling fast candidate retrieval with zero per-check API costs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.lexical import SourceDocument
from pipeline.normalize import tokenize_with_offsets


@dataclass
class CorpusItem:
    id: int
    title: str
    text: str
    kind: str = "corpus"
    year: int | None = None
    url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class LocalCorpusIndex:
    """In-memory inverted index of reference documents stored on worker disk."""

    def __init__(self, n_gram_size: int = 5) -> None:
        self.n_gram_size = n_gram_size
        self.documents: dict[int, SourceDocument] = {}
        self.metadata: dict[int, CorpusItem] = {}
        # Inverted index: word -> set of document IDs
        self.inverted_index: dict[str, set[int]] = {}

    def add_document(
        self,
        doc_id: int,
        title: str,
        text: str,
        kind: str = "corpus",
        year: int | None = None,
        url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SourceDocument:
        """Add a document to the index and update the inverted index."""
        src_doc = SourceDocument.from_text(
            source_id=doc_id,
            label=title,
            text=text,
            kind=kind,
            n_gram_size=self.n_gram_size,
        )
        self.documents[doc_id] = src_doc
        self.metadata[doc_id] = CorpusItem(
            id=doc_id,
            title=title,
            text=text,
            kind=kind,
            year=year,
            url=url,
            metadata=metadata or {},
        )

        # Index individual words for candidate pre-filtering
        tokens = tokenize_with_offsets(text)
        unique_words = {t.norm for t in tokens if len(t.norm) > 3}
        for word in unique_words:
            if word not in self.inverted_index:
                self.inverted_index[word] = set()
            self.inverted_index[word].add(doc_id)

        return src_doc

    def search_candidates(
        self,
        query_words: list[str],
        top_k: int = 15,
        min_overlap: int = 3,
    ) -> list[SourceDocument]:
        """Fast lexical candidate filtering using inverted index word overlap."""
        doc_scores: dict[int, int] = {}
        clean_query = {w.lower() for w in query_words if len(w) > 3}

        for word in clean_query:
            if word in self.inverted_index:
                for doc_id in self.inverted_index[word]:
                    doc_scores[doc_id] = doc_scores.get(doc_id, 0) + 1

        # Filter by minimum word overlap and sort by score
        candidates = [
            (doc_id, score)
            for doc_id, score in doc_scores.items()
            if score >= min_overlap
        ]
        candidates.sort(key=lambda x: x[1], reverse=True)

        return [self.documents[doc_id] for doc_id, _ in candidates[:top_k]]

    def load_from_json(self, file_path: Path | str) -> int:
        """Load corpus documents from a JSON file."""
        p = Path(file_path)
        if not p.exists():
            return 0
        data = json.loads(p.read_text(encoding="utf-8"))
        count = 0
        items = data if isinstance(data, list) else data.get("documents", data.get("reference_corpus", []))
        for item in items:
            self.add_document(
                doc_id=item.get("id", len(self.documents) + 1),
                title=item.get("title", f"Document {item.get('id', count + 1)}"),
                text=item.get("text", ""),
                kind=item.get("kind", "corpus"),
                year=item.get("year"),
                url=item.get("url"),
                metadata=item.get("metadata", {}),
            )
            count += 1
        return count

    def get_all_documents(self) -> list[SourceDocument]:
        """Return all indexed documents."""
        return list(self.documents.values())

    def __len__(self) -> int:
        return len(self.documents)
