"""Public API for the guardrails subsystem."""

from backend.guardrails.groundedness import (
    verify_groundedness,
    apply_groundedness_to_confidence,
)
from backend.guardrails.injection_scanner import (
    scan_text_for_injection,
    classify_injection,
    scan_chunk,
)
from backend.guardrails.severity import is_high_stakes, get_escalation_notice
from backend.guardrails.pii import redact_pii
from backend.guardrails.audit_log import (
    log_injection_attempt,
    log_injection_flagged,
    log_high_stakes_query,
)

__all__ = [
    "verify_groundedness",
    "apply_groundedness_to_confidence",
    "scan_text_for_injection",
    "classify_injection",
    "scan_chunk",
    "is_high_stakes",
    "get_escalation_notice",
    "redact_pii",
    "log_injection_attempt",
    "log_injection_flagged",
    "log_high_stakes_query",
]
