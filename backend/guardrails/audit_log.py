"""
Append-only JSONL audit writers for injection attempts and severity escalations.

All writes are synchronous, guarded by a module-level lock to prevent
interleaved lines under concurrent async requests. Logging failures
never propagate — the audit trail must not block the main pipeline.
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone

from backend.config import settings
from backend.guardrails.pii import redact_obj

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()


def _resolve_path(filename: str) -> str:
    """Build the full audit file path from the configured audit directory."""
    return os.path.join(settings.AUDIT_DIR, filename)


def _append(path: str, record: dict) -> None:
    """Append a single timestamped JSON record to a JSONL file. Never raises.
    Every string field is PII-redacted before it is written."""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        record = redact_obj(record)
        record["_logged_at"] = datetime.now(timezone.utc).isoformat()
        line = json.dumps(record, default=str) + "\n"
        with _write_lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        logger.exception("Failed to write audit record to %s", path)


# ── Injection audit ──────────────────────────────────────────────────────────

_INJECTION_LOG = "injection_audit.jsonl"


def log_injection_attempt(
    chunk_id: str,
    doc_id: str,
    file_name: str,
    text_preview: str,
    matched_patterns: list[str],
    llm_reasoning: str,
) -> None:
    """Log a confirmed injection attempt (LLM classifier returned True)."""
    _append(_resolve_path(_INJECTION_LOG), {
        "event": "injection_confirmed",
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "file_name": file_name,
        "text_preview": text_preview[:200],
        "matched_patterns": matched_patterns,
        "llm_reasoning": llm_reasoning,
    })


def log_injection_flagged(
    chunk_id: str,
    doc_id: str,
    file_name: str,
    matched_patterns: list[str],
) -> None:
    """Log a regex-flagged chunk that was cleared by the LLM classifier."""
    _append(_resolve_path(_INJECTION_LOG), {
        "event": "injection_flagged_cleared",
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "file_name": file_name,
        "matched_patterns": matched_patterns,
    })


# ── Human review audit ───────────────────────────────────────────────────────

_REVIEW_LOG = "review_audit.jsonl"


def log_review_event(event: str, review_id: str, **fields) -> None:
    """Log a review lifecycle event ("review_pending" / "review_decision"),
    including reviewer identity and decision for decisions."""
    _append(_resolve_path(_REVIEW_LOG), {"event": event, "review_id": review_id, **fields})


# ── Escalation audit ─────────────────────────────────────────────────────────

_ESCALATION_LOG = "escalation_audit.jsonl"


def log_high_stakes_query(
    query: str,
    confidence: float,
    confidence_label: str,
    escalated: bool,
    escalation_notice: str = "",
) -> None:
    """Log every high-stakes query regardless of whether escalation fired."""
    _append(_resolve_path(_ESCALATION_LOG), {
        "event": "high_stakes_query",
        "query": query,
        "confidence": confidence,
        "confidence_label": confidence_label,
        "escalated": escalated,
        "escalation_notice": escalation_notice,
    })
