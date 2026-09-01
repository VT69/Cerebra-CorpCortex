"""
Audit log writers — shared by injection scanner and severity escalation.

All audit entries are append-only JSONL files stored under ./data/.
Each entry is a single JSON object per line, timestamped.
Never raises — logging failures must never block the main pipeline.
"""
import json
import os
from datetime import datetime, timezone

# Audit file paths — relative to wherever the app is run from (project root)
INJECTION_AUDIT_PATH = "./data/injection_audit.jsonl"
ESCALATION_AUDIT_PATH = "./data/escalation_audit.jsonl"


def _ensure_dir(path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)


def _append(path: str, record: dict):
    """Append a single JSON record to a JSONL audit file. Never raises."""
    try:
        _ensure_dir(path)
        record["_logged_at"] = datetime.now(timezone.utc).isoformat()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        print(f"[AuditLog] Failed to write to {path}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Injection audit
# ─────────────────────────────────────────────────────────────────────────────

def log_injection_attempt(
    chunk_id: str,
    doc_id: str,
    file_name: str,
    text_preview: str,
    matched_patterns: list[str],
    llm_reasoning: str,
):
    """
    Log a confirmed injection attempt to the injection audit file.
    Only called when LLM classifier confirms is_injection_attempt == True.
    """
    _append(INJECTION_AUDIT_PATH, {
        "event": "injection_attempt_confirmed",
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
):
    """
    Log a regex-flagged (but LLM-cleared) chunk. Useful for tuning patterns.
    """
    _append(INJECTION_AUDIT_PATH, {
        "event": "injection_flagged_cleared",
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "file_name": file_name,
        "matched_patterns": matched_patterns,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Escalation audit
# ─────────────────────────────────────────────────────────────────────────────

def log_high_stakes_query(
    query: str,
    confidence: float,
    confidence_label: str,
    escalated: bool,
    escalation_notice: str = "",
):
    """
    Log every high-stakes query with its final confidence and whether
    an escalation notice was shown to the user.
    """
    _append(ESCALATION_AUDIT_PATH, {
        "event": "high_stakes_query",
        "query": query,
        "confidence": confidence,
        "confidence_label": confidence_label,
        "escalated": escalated,
        "escalation_notice": escalation_notice,
    })
