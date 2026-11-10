"""Basic AI-generated text heuristic indicator.

Calculates burstiness (variance of sentence lengths), vocabulary diversity entropy,
and characteristic AI transitional cliches to provide an educational indication
of potential AI-assisted writing.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from pipeline.normalize import get_sentence_spans

# Characteristic phrases frequently overrepresented in AI-generated drafts
AI_CLICHE_PATTERNS = [
    re.compile(r"\bdelve(?:s|d)?\s+into\b", re.IGNORECASE),
    re.compile(r"\ba\s+testament\s+to\b", re.IGNORECASE),
    re.compile(r"\bplays\s+a\s+(?:crucial|pivotal|vital|key)\s+role\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+(?:important|worth|crucial|essential)\s+to\s+note\b", re.IGNORECASE),
    re.compile(r"\btapestry\s+of\b", re.IGNORECASE),
    re.compile(r"\bin\s+today's\s+(?:fast-paced|rapidly\s+evolving|interconnected|modern)\s+world\b", re.IGNORECASE),
    re.compile(r"\bserves\s+as\s+a\s+(?:reminder|beacon|foundation)\b", re.IGNORECASE),
    re.compile(r"\bparamount\s+importance\b", re.IGNORECASE),
    re.compile(r"\bmultifaceted\s+nature\b", re.IGNORECASE),
    re.compile(r"\bby\s+fostering\s+a\b", re.IGNORECASE),
    re.compile(r"\bin\s+conclusion\b", re.IGNORECASE),
    re.compile(r"\bnot\s+only\s+.+\s+but\s+also\b", re.IGNORECASE),
]


@dataclass
class AiDetectionResult:
    likelihood: str  # "Likely Human", "Mixed / Uncertain", "Elevated AI Markers"
    score: float  # 0.0 to 1.0
    burstiness: float  # Standard deviation of sentence word counts
    cliche_count: int
    flags: list[str] = field(default_factory=list)


def analyze_ai_indicators(text: str) -> AiDetectionResult:
    """Analyze sentence burstiness and stylistic markers to evaluate AI writing characteristics."""
    sentences = get_sentence_spans(text)
    if len(sentences) < 5:
        return AiDetectionResult(
            likelihood="Likely Human",
            score=0.1,
            burstiness=10.0,
            cliche_count=0,
            flags=[],
        )

    # 1. Burstiness analysis (sentence length variation)
    sent_word_counts = [len(re.findall(r"\w+", s.text)) for s in sentences if len(s.text.strip()) > 5]
    if len(sent_word_counts) < 5:
        return AiDetectionResult(
            likelihood="Likely Human",
            score=0.1,
            burstiness=10.0,
            cliche_count=0,
            flags=[],
        )

    mean_len = sum(sent_word_counts) / float(len(sent_word_counts))
    variance = sum((x - mean_len) ** 2 for x in sent_word_counts) / float(len(sent_word_counts))
    std_dev = math.sqrt(variance)

    # 2. AI Cliche frequency
    cliche_hits = 0
    for pat in AI_CLICHE_PATTERNS:
        cliche_hits += len(pat.findall(text))

    # Normalized cliche density per 500 words
    total_words = sum(sent_word_counts)
    cliche_density = (cliche_hits / float(total_words)) * 500.0 if total_words else 0.0

    # 3. Score calculation
    # Low std_dev (< 4.0) means mechanical uniform sentence length -> higher AI likelihood
    burstiness_score = max(0.0, min(1.0, (8.0 - std_dev) / 8.0))
    cliche_score = min(1.0, cliche_density / 3.0)

    combined_score = round((0.60 * burstiness_score) + (0.40 * cliche_score), 2)

    flags: list[str] = []
    if combined_score >= 0.70 and cliche_hits >= 3:
        likelihood = "Elevated AI Markers"
        flags.append(
            f"Stylistic audit note: Uniform sentence cadence (burstiness: {std_dev:.1f}) and {cliche_hits} characteristic AI transitional phrases detected"
        )
    elif combined_score >= 0.45:
        likelihood = "Mixed / Uncertain"
    else:
        likelihood = "Likely Human"

    return AiDetectionResult(
        likelihood=likelihood,
        score=combined_score,
        burstiness=round(std_dev, 2),
        cliche_count=cliche_hits,
        flags=flags,
    )
