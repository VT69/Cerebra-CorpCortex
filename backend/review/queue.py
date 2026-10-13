"""
Review queue for high-stakes answers held by the LangGraph interrupt.

The paused graph state (draft answer, citations, confidence) lives in the
LangGraph SQLite checkpointer, keyed by thread_id == review_id. This table
only tracks lifecycle so reviewers can list what is pending and a decision
can be claimed exactly once.
"""
import sqlite3
import threading
from datetime import datetime, timezone

from backend.config import settings

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_queue (
    review_id   TEXT PRIMARY KEY,
    question    TEXT NOT NULL,
    status      TEXT NOT NULL,           -- pending_review | deciding | approved | edited | rejected
    created_at  TEXT NOT NULL,
    reviewer    TEXT,
    decided_at  TEXT
)
"""


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(settings.CHECKPOINT_DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute(_SCHEMA)
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_pending(review_id: str, question: str) -> None:
    with _lock, _conn() as con:
        con.execute("INSERT INTO review_queue (review_id, question, status, created_at) VALUES (?, ?, ?, ?)",
                    (review_id, question, "pending_review", _now()))


def get(review_id: str) -> dict | None:
    with _lock, _conn() as con:
        row = con.execute("SELECT * FROM review_queue WHERE review_id = ?", (review_id,)).fetchone()
    return dict(row) if row else None


def list_pending() -> list[dict]:
    with _lock, _conn() as con:
        rows = con.execute(
            "SELECT * FROM review_queue WHERE status = 'pending_review' ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def claim(review_id: str, reviewer: str) -> bool:
    """Atomically move pending -> deciding. False if already decided/claimed."""
    with _lock, _conn() as con:
        cur = con.execute(
            "UPDATE review_queue SET status = 'deciding', reviewer = ? "
            "WHERE review_id = ? AND status = 'pending_review'", (reviewer, review_id))
    return cur.rowcount == 1


def release_claim(review_id: str) -> None:
    """Return a claimed item to the queue if resuming the graph failed."""
    with _lock, _conn() as con:
        con.execute("UPDATE review_queue SET status = 'pending_review', reviewer = NULL "
                    "WHERE review_id = ? AND status = 'deciding'", (review_id,))


def finish(review_id: str, status: str) -> None:
    with _lock, _conn() as con:
        con.execute("UPDATE review_queue SET status = ?, decided_at = ? WHERE review_id = ?",
                    (status, _now(), review_id))
