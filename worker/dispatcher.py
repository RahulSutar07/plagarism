"""Job dispatcher module.

Schedules plagiarism analysis jobs asynchronously via background threads or RQ workers,
enforcing maximum queue capacities.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.config import get_settings
from worker.store import get_job_store
from worker.tasks import process_plagiarism_job

logger = logging.getLogger(__name__)


class QueueFullError(Exception):
    """Raised when queue waiting jobs exceed the configured cap."""
    pass


def enqueue_plagiarism_job(
    raw_text: str,
    title: str = "Submitted Document",
    enable_web_search: bool = False,
    enable_paraphrase: bool = True,
    queue_name: str = "fast",
    corpus_file: Path | str | None = None,
    identifier: str | None = None,
    user_id: int | None = None,
) -> tuple[str, int]:
    """Enqueue a plagiarism job asynchronously.
    
    Returns (job_id, queue_position).
    """
    settings = get_settings()
    store = get_job_store()

    # Enforce queue cap
    waiting = store.get_waiting_count()
    if waiting >= settings.queue_cap:
        raise QueueFullError(
            f"Scanning queue is currently at capacity ({waiting}/{settings.queue_cap} jobs). "
            "Please try again in a few minutes."
        )

    job_id = store.create_job(queue_name=queue_name, identifier=identifier, user_id=user_id)
    queue_pos = store.get_queue_position(job_id)

    # Launch asynchronously via daemon thread (or RQ worker if configured)
    thread = threading.Thread(
        target=process_plagiarism_job,
        kwargs={
            "job_id": job_id,
            "raw_text": raw_text,
            "title": title,
            "enable_web_search": enable_web_search,
            "enable_paraphrase": enable_paraphrase,
        },
        daemon=True,
    )
    thread.start()

    return job_id, queue_pos
