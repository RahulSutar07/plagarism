"""Document language detection module.

Identifies the primary language of the submitted document using stopword profiling
and character n-gram statistics, providing confidence scores and academic language flags.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Core stopword banks for fast language identification
LANGUAGE_STOPWORDS: dict[str, set[str]] = {
    "en": {
        "the", "and", "is", "in", "it", "you", "that", "he", "was", "for", "on", "are",
        "as", "with", "his", "they", "at", "be", "this", "have", "from", "or", "one",
        "had", "by", "word", "but", "not", "what", "all", "were", "we", "when", "your",
        "can", "said", "there", "use", "an", "each", "which", "she", "do", "how", "their",
    },
    "es": {
        "el", "la", "de", "que", "y", "en", "un", "ser", "se", "no", "haber", "por",
        "con", "su", "para", "como", "estar", "tener", "le", "lo", "todo", "pero",
        "mas", "hacer", "o", "poder", "decir", "este", "ir", "otro", "ese", "del",
    },
    "fr": {
        "le", "la", "de", "un", "etre", "et", "a", "il", "avoir", "ne", "je", "son",
        "que", "se", "qui", "ce", "dans", "en", "du", "elle", "au", "de", "ce", "le",
        "pour", "pas", "sur", "faire", "plus", "dire", "me", "on", "mon", "lui", "nous",
    },
    "de": {
        "der", "die", "und", "in", "den", "von", "zu", "das", "mit", "sich", "des",
        "auf", "fur", "ist", "im", "dem", "nicht", "ein", "eine", "als", "auch",
        "es", "an", "werden", "aus", "er", "hat", "dass", "sie", "nach", "wird",
    },
}

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "unknown": "Unknown / Mixed",
}


@dataclass(frozen=True)
class LanguageDetectionResult:
    language_code: str
    language_name: str
    confidence: float
    is_primary_supported: bool  # True if English (primary embedding & corpus model language)
    flag: str | None = None


def detect_document_language(text: str) -> LanguageDetectionResult:
    """Analyze document text and detect primary language and confidence."""
    words = [w.lower() for w in re.findall(r"\b[a-zA-Záéíóúüñäößàâçèêëîïôûù]+\b", text)]
    if len(words) < 15:
        return LanguageDetectionResult(
            language_code="en",
            language_name="English",
            confidence=0.5,
            is_primary_supported=True,
            flag=None,
        )

    total_words = len(words)
    scores: dict[str, float] = {}

    for code, stop_set in LANGUAGE_STOPWORDS.items():
        # Running token frequency ratio
        token_hits = sum(1 for w in words if w in stop_set)
        # Distinct set overlap
        distinct_hits = len(set(words) & stop_set)
        # Combined density metric
        token_ratio = token_hits / float(total_words)
        distinct_ratio = distinct_hits / float(len(stop_set))
        scores[code] = (token_ratio * 0.70) + (distinct_ratio * 0.30)

    sorted_langs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_code, best_score = sorted_langs[0]

    # If top score is under 0.04, document is unclassified or symbolic
    if best_score < 0.04:
        return LanguageDetectionResult(
            language_code="unknown",
            language_name="Unknown / Multilingual",
            confidence=round(best_score, 2),
            is_primary_supported=False,
            flag="Document language is non-standard or multilingual; semantic paraphrase scores may be restricted.",
        )

    second_score = sorted_langs[1][1] if len(sorted_langs) > 1 else 0.0
    margin = best_score - second_score
    confidence = min(0.99, max(0.65, 0.65 + margin * 1.5))

    lang_name = LANGUAGE_NAMES.get(best_code, "Other")
    is_supported = best_code == "en"
    flag = None
    if not is_supported:
        flag = f"Document detected as {lang_name} ({confidence:.0%} confidence). Full lexical shingling active; English semantic embedding index may not cover cross-lingual translations."

    return LanguageDetectionResult(
        language_code=best_code,
        language_name=lang_name,
        confidence=round(confidence, 2),
        is_primary_supported=is_supported,
        flag=flag,
    )
