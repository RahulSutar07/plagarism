"""Semantic and paraphrase detection module using dense neural embeddings.

Employs Sentence-Transformers ('all-MiniLM-L6-v2') to catch restructured sentences and heavy paraphrases.
Applies the mandatory Dual-Signal Rule (Cosine Similarity >= 0.85 AND Content Word Jaccard >= 0.20)
to prevent false accusations on common generic ideas.
"""
from __future__ import annotations

import bisect
import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Literal

from pipeline.lexical import MatchSpan, SourceDocument
from pipeline.normalize import SentenceSpan, Token, get_sentence_spans

logger = logging.getLogger(__name__)

# Common English stopwords to filter out when calculating structural content overlap
STOPWORDS = frozenset(
    """a an the and or but of in on at to for with by from as is are was were be been
it this that these those which who whom their its his her our your we they he she i
not no can could would should may might will shall do does did has have had than then
so such also into over under between about more most other some any""".split()
)

_cached_model = None
_model_load_failed = False


def get_embedding_model(model_name: str = "all-MiniLM-L6-v2"):
    """Load and cache the SentenceTransformer model in memory."""
    global _cached_model, _model_load_failed
    if _model_load_failed:
        return None
    if _cached_model is None:
        from sentence_transformers import SentenceTransformer
        # Try local cache first to avoid hanging on network timeouts
        try:
            _cached_model = SentenceTransformer(model_name, local_files_only=True)
            return _cached_model
        except Exception:
            pass

        # Attempt download only if network is reachable with fast timeout
        import socket
        try:
            with socket.create_connection(("huggingface.co", 443), timeout=1.0):
                pass
            _cached_model = SentenceTransformer(model_name)
        except Exception as e:
            logger.warning("Could not load SentenceTransformer model '%s' (running in offline/lexical mode): %s", model_name, e)
            _model_load_failed = True
            return None
    return _cached_model


@dataclass
class ParaphraseMatch:
    doc_sentence_idx: int
    source_id: int
    doc_text: str
    source_text: str
    cosine_similarity: float
    content_jaccard: float
    token_start_idx: int
    token_end_idx: int
    char_start: int
    char_end: int


@dataclass
class SemanticResult:
    detected_paraphrases: list[ParaphraseMatch] = field(default_factory=list)
    paraphrase_word_count: int = 0
    new_spans: list[MatchSpan] = field(default_factory=list)


def compute_content_jaccard(text_a: str, text_b: str) -> float:
    """Compute Jaccard similarity over non-stopword content words (Signal 2)."""
    words_a = {
        w for w in re.findall(r"\w+", text_a.lower()) if w not in STOPWORDS and len(w) > 2
    }
    words_b = {
        w for w in re.findall(r"\w+", text_b.lower()) if w not in STOPWORDS and len(w) > 2
    }
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / float(len(union))


def detect_paraphrase_pass(
    text: str,
    tokens: list[Token],
    sources: list[SourceDocument],
    token_ownership: dict[int, tuple[int, Literal["exact", "near", "paraphrase"]]],
    is_excluded_fn: Callable[[int], bool] | None = None,
    sentences: list[SentenceSpan] | None = None,
    min_cosine_threshold: float = 0.85,
    min_jaccard_threshold: float = 0.20,
    model_name: str = "all-MiniLM-L6-v2",
) -> SemanticResult:
    """Run semantic paraphrase matching pass on sentences not already covered by lexical matching."""
    if not tokens or not sources:
        return SemanticResult()

    if sentences is None:
        sentences = get_sentence_spans(text)

    token_starts = [t.start for t in tokens]
    total_tokens = len(tokens)

    # 1. Identify scorable candidate sentences not already covered by exact/near matching
    candidates: list[tuple[int, int, int, list[int], str]] = []  # (sent_idx, token_a, token_b, scorable_tokens, text)
    for sent_idx, s in enumerate(sentences):
        a = bisect.bisect_left(token_starts, s.start)
        b = bisect.bisect_left(token_starts, s.end)

        total_in_sent = b - a
        scorable_tokens = [
            k for k in range(a, b) if not (is_excluded_fn and is_excluded_fn(tokens[k].start))
        ]
        # Skip sentences with fewer than 8 scorable words or where >50% of words are excluded citations/quotes
        if len(scorable_tokens) < 8 or (total_in_sent > 0 and (len(scorable_tokens) / float(total_in_sent)) < 0.50):
            continue

        # Use scorable words for semantic candidate text
        scorable_text = " ".join(tokens[k].text for k in scorable_tokens)

        # Check existing lexical coverage in this sentence
        lexical_hits = sum(1 for k in scorable_tokens if k in token_ownership)
        if (lexical_hits / float(len(scorable_tokens))) < 0.30:
            candidates.append((sent_idx, a, b, scorable_tokens, scorable_text))

    if not candidates:
        return SemanticResult()

    # 2. Extract reference sentences from source documents
    src_sentences: list[tuple[int, str]] = []  # (source_id, sent_text)
    for src in sources:
        for s in get_sentence_spans(src.text):
            words = s.text.split()
            if 8 <= len(words) <= 70:
                src_sentences.append((src.source_id, s.text))

    if not src_sentences:
        return SemanticResult()

    # Limit search space for memory protection
    src_sentences = src_sentences[:10000]

    # 3. Dense embeddings
    model = get_embedding_model(model_name)
    if model is None:
        # Graceful fallback: model unavailable offline, return clean result
        return SemanticResult()
    cand_texts = [c[4] for c in candidates]
    src_texts = [s[1] for s in src_sentences]

    # Normalize embeddings for direct cosine similarity via dot product
    cand_embs = model.encode(cand_texts, normalize_embeddings=True, show_progress_bar=False)
    src_embs = model.encode(src_texts, normalize_embeddings=True, show_progress_bar=False)

    similarity_matrix = cand_embs @ src_embs.T

    # 4. Evaluate Dual-Signal criteria
    detected_paraphrases: list[ParaphraseMatch] = []
    new_spans: list[MatchSpan] = []
    total_paraphrase_words = 0

    for ci, (sent_idx, a, b, scorable_tokens, cand_text) in enumerate(candidates):
        best_src_idx = int(similarity_matrix[ci].argmax())
        best_cosine = float(similarity_matrix[ci, best_src_idx])

        # Signal 1: Cosine similarity threshold
        if best_cosine < min_cosine_threshold:
            continue

        target_src_id, target_src_text = src_sentences[best_src_idx]

        # Signal 2: Content word Jaccard overlap threshold
        jaccard = compute_content_jaccard(cand_text, target_src_text)
        if jaccard < min_jaccard_threshold:
            continue

        # Both signals passed -> record paraphrase hit
        match = ParaphraseMatch(
            doc_sentence_idx=sent_idx,
            source_id=target_src_id,
            doc_text=cand_text,
            source_text=target_src_text,
            cosine_similarity=round(best_cosine, 3),
            content_jaccard=round(jaccard, 3),
            token_start_idx=a,
            token_end_idx=b,
            char_start=tokens[a].start,
            char_end=tokens[b - 1].end if b <= total_tokens else tokens[-1].end,
        )
        detected_paraphrases.append(match)

        # Mark token ownership only for scorable tokens
        words_claimed = 0
        for k in scorable_tokens:
            if k not in token_ownership:
                token_ownership[k] = (target_src_id, "paraphrase")
                words_claimed += 1

        if words_claimed > 0:
            total_paraphrase_words += words_claimed
            new_spans.append(
                MatchSpan(
                    start_token_idx=a,
                    end_token_idx=b,
                    start_char=match.char_start,
                    end_char=match.char_end,
                    source_id=target_src_id,
                    match_type="paraphrase",
                    matched_word_count=words_claimed,
                )
            )

    return SemanticResult(
        detected_paraphrases=detected_paraphrases,
        paraphrase_word_count=total_paraphrase_words,
        new_spans=new_spans,
    )
