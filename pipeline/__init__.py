"""Detection pipeline package.

Exposes core document extraction, anti-evasion normalization, exclusions,
sliding chunk windows, lexical matching, semantic paraphrase detection,
candidate retrieval, and combined scoring.
"""
from pipeline.chunk import SentenceWindow, create_sentence_windows, extract_candidate_queries
from pipeline.evasion import EvasionResult, detect_and_clean_evasion
from pipeline.exclude import ExclusionReport, ExclusionSpan, find_exclusions
from pipeline.extract import ExtractionError, ExtractionResult, extract_document
from pipeline.lexical import (
    LexicalMatchResult,
    MatchSpan,
    SourceDocument,
    SourceMatchSummary,
    find_shingle_matches,
    match_document_lexical,
)
from pipeline.normalize import SentenceSpan, Token, get_sentence_spans, normalize_string, tokenize_with_offsets
from pipeline.retrieve import RetrievalResult, retrieve_candidates, search_web_candidates
from pipeline.score import CombinedAnalysisResult, analyze_document
from pipeline.semantic import ParaphraseMatch, SemanticResult, compute_content_jaccard, detect_paraphrase_pass
from pipeline.sources import fetch_web_page, is_robots_allowed

__all__ = [
    "extract_document",
    "ExtractionResult",
    "ExtractionError",
    "detect_and_clean_evasion",
    "EvasionResult",
    "normalize_string",
    "tokenize_with_offsets",
    "get_sentence_spans",
    "Token",
    "SentenceSpan",
    "find_exclusions",
    "ExclusionSpan",
    "ExclusionReport",
    "create_sentence_windows",
    "extract_candidate_queries",
    "SentenceWindow",
    "SourceDocument",
    "MatchSpan",
    "SourceMatchSummary",
    "LexicalMatchResult",
    "find_shingle_matches",
    "match_document_lexical",
    "detect_paraphrase_pass",
    "compute_content_jaccard",
    "SemanticResult",
    "ParaphraseMatch",
    "analyze_document",
    "CombinedAnalysisResult",
    "retrieve_candidates",
    "RetrievalResult",
    "search_web_candidates",
    "fetch_web_page",
    "is_robots_allowed",
]
