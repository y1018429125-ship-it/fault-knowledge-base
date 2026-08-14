"""QA session logger: append one JSON line per query to logs/qa.jsonl.

Each record captures the full question/answer and per-stage latency so
answer-quality and latency issues can be diagnosed from the same file.
Standard library only; low volume (local single-user), no rotation.
"""

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs",
    "qa.jsonl",
)

_write_lock = threading.Lock()


def new_request_id() -> str:
    """Short unique ID for correlating one QA session."""
    return uuid.uuid4().hex[:12]


def log_qa(record: dict[str, Any]) -> None:
    """Append one QA record as a JSON line. Never raises into the caller."""
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **record}
    try:
        line = json.dumps(record, ensure_ascii=False)
        with _write_lock:
            os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except OSError as exc:
        print(f"[qa_logger] failed to write {LOG_PATH}: {exc}")
