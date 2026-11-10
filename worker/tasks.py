"""Background worker tasks for asynchronous plagiarism check execution."""
from __future__ import annotations

import logging
from pathlib import Path

from app.config import get_settings
from app.schemas import MatchSpanSchema, ScanResultSummary, SourceSummarySchema
from index.corpus import LocalCorpusIndex
from pipeline.ai_detect import analyze_ai_indicators
from pipeline.evasion import detect_and_clean_evasion
from pipeline.language import detect_document_language
from pipeline.lexical import SourceDocument
from pipeline.normalize import get_sentence_spans, tokenize_with_offsets
from pipeline.retrieve import retrieve_candidates
from pipeline.score import analyze_document
from worker.store import get_job_store

logger = logging.getLogger(__name__)

DEFAULT_CORPUS_FILE = Path(__file__).parent.parent / "eval" / "datasets" / "benchmark_data.json"


def process_plagiarism_job(
    job_id: str,
    raw_text: str,
    title: str = "Submitted Document",
    enable_web_search: bool = False,
    enable_paraphrase: bool = True,
    corpus_file: Path | str = DEFAULT_CORPUS_FILE,
) -> None:
    """Execute asynchronous plagiarism analysis pipeline and update job store."""
    store = get_job_store()
    settings = get_settings()

    try:
        # Stage 1: Sanitization & Anti-Evasion
        store.update_job(job_id, status="processing", stage="sanitizing", progress_pct=15)
        evasion_res = detect_and_clean_evasion(raw_text)
        cleaned_text = evasion_res.cleaned_text

        # Word count check
        tokens = tokenize_with_offsets(cleaned_text)
        word_count = len(tokens)
        if word_count < settings.min_words:
            store.update_job(
                job_id,
                status="failed",
                stage="failed",
                error=f"Document contains only {word_count} words; minimum required is {settings.min_words}.",
            )
            return

        # Stage 2: Candidate Retrieval
        store.update_job(job_id, stage="retrieving", progress_pct=40)
        sentences = get_sentence_spans(cleaned_text)

        # Self-plagiarism: query author's previous completed submissions
        self_sources: list[SourceDocument] = []
        job_record = store.get_job(job_id)
        user_id = job_record.user_id if job_record else None
        if user_id:
            try:
                from app.database import SessionLocal
                from app.models import Job as DBJob, ScanResult as DBScanResult
                with SessionLocal() as db:
                    prev_scans = (
                        db.query(DBScanResult)
                        .join(DBJob)
                        .filter(DBJob.user_id == user_id, DBJob.id != job_id, DBScanResult.raw_text.is_not(None))
                        .limit(5)
                        .all()
                    )
                    for prev in prev_scans:
                        if prev.raw_text and len(prev.raw_text.split()) >= 30:
                            self_doc = SourceDocument.from_text(
                                source_id=len(self_sources) + 900,
                                label=f"Author Previous Submission: {prev.title}",
                                text=prev.raw_text,
                                kind="self",
                            )
                            self_sources.append(self_doc)
            except Exception as e:
                logger.debug("Self-plagiarism query error: %s", e)

        # Load reference corpus
        corpus_index = LocalCorpusIndex()
        if Path(corpus_file).exists():
            corpus_index.load_from_json(corpus_file)

        retrieval_res = retrieve_candidates(
            doc_text=cleaned_text,
            tokens=tokens,
            sentences=sentences,
            local_corpus=corpus_index,
            extra_sources=self_sources,
            enable_web_search=enable_web_search,
        )

        # Stage 3: Lexical & Semantic Matching
        store.update_job(job_id, stage="matching", progress_pct=70)
        analysis = analyze_document(
            text=cleaned_text,
            sources=retrieval_res.sources,
            enable_paraphrase=enable_paraphrase,
        )

        # Combine audit flags
        all_flags = evasion_res.flags + analysis.flags
        if retrieval_res.is_partial:
            all_flags.append(f"Partial scan: {retrieval_res.partial_reason}")

        # Document language detection
        lang_res = detect_document_language(cleaned_text)
        if lang_res.flag:
            all_flags.append(lang_res.flag)
        else:
            all_flags.append(f"Language: {lang_res.language_name} ({lang_res.confidence:.0%} confidence)")

        # AI-assisted writing indicators
        ai_res = analyze_ai_indicators(cleaned_text)
        if ai_res.flags:
            all_flags.extend(ai_res.flags)
        else:
            all_flags.append(f"AI Content Indicator: {ai_res.likelihood} (sentence cadence: {ai_res.burstiness:.1f})")

        # Self-plagiarism alert
        self_matches = [s for s in analysis.source_summaries if s.kind == "self"]
        if self_matches:
            self_total = sum(s.percentage for s in self_matches)
            all_flags.append(f"Self-Plagiarism Alert: {self_total:.1f}% matches earlier submissions by the same author")

        # Map MatchSpans to schema
        match_spans = [
            MatchSpanSchema(
                start_token_idx=m.start_token_idx,
                end_token_idx=m.end_token_idx,
                start_char=m.start_char,
                end_char=m.end_char,
                source_id=m.source_id,
                match_type=m.match_type,
                matched_word_count=m.matched_word_count,
            )
            for m in analysis.match_spans
        ]

        # Map SourceSummaries to schema
        source_summaries = [
            SourceSummarySchema(
                source_id=s.source_id,
                label=s.label,
                kind=s.kind,
                matched_words=s.matched_words,
                percentage=s.percentage,
                confidence=s.confidence,
                longest_contiguous_run=s.longest_contiguous_run,
            )
            for s in analysis.source_summaries
        ]

        result_summary = ScanResultSummary(
            title=title,
            overall_similarity_pct=analysis.overall_similarity_pct,
            exact_pct=analysis.exact_pct,
            near_pct=analysis.near_pct,
            paraphrase_pct=analysis.paraphrase_pct,
            total_words=analysis.total_words,
            scored_words=analysis.scored_words,
            matched_words=analysis.matched_words,
            largest_single_source=analysis.largest_single_source,
            is_partial=retrieval_res.is_partial,
            partial_reason=retrieval_res.partial_reason,
            searched_description=retrieval_res.searched_description,
            flags=all_flags,
            source_summaries=source_summaries,
            match_spans=match_spans,
            cleaned_text=cleaned_text,
        )

        # Discard raw text to respect data minimization
        raw_text = ""
        cleaned_text = ""

        # Mark completed
        store.update_job(
            job_id,
            status="completed",
            stage="completed",
            progress_pct=100,
            result=result_summary,
        )

    except Exception as e:
        logger.exception("Error processing plagiarism job %s", job_id)
        store.update_job(
            job_id,
            status="failed",
            stage="failed",
            error=f"Internal scanning error: {str(e)[:180]}",
        )
