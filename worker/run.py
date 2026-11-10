"""RQ worker entrypoint.  Usage: python -m worker.run fast   |   python -m worker.run ocr

Phase 0: starts and idles on the queue. Job functions arrive in Phase 5.
"""
import sys

from redis import Redis
from rq import Queue, Worker

from app.config import get_settings


def main() -> None:
    s = get_settings()
    name = sys.argv[1] if len(sys.argv) > 1 else s.fast_queue
    if name not in (s.fast_queue, s.ocr_queue):
        raise SystemExit(f"Unknown queue '{name}'. Use '{s.fast_queue}' or '{s.ocr_queue}'.")
    conn = Redis.from_url(s.redis_url)
    Worker([Queue(name, connection=conn)], connection=conn).work()


if __name__ == "__main__":
    main()
