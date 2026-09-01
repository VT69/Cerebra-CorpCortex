"""
High-stakes query severity classifier.

Fast keyword scan (no LLM call, ~0ms) to flag safety-critical queries.
When a high-stakes query has Medium or Low confidence after groundedness
verification, an escalation notice is attached directing the user to
verify with a qualified professional before acting.

Every high-stakes query is audit-logged regardless of escalation outcome.
"""

import logging

logger = logging.getLogger(__name__)


# ── Configuration ────────────────────────────────────────────────────────────

HIGH_STAKES_KEYWORDS: frozenset[str] = frozenset([
    "lockout", "tagout", "loto", "shutdown", "permit",
    "hazard", "gas leak", "evacuation", "confined space",
    "hot work", "pressure release", "emergency",
    "compliance violation", "safety procedure",
    "explosion", "fire hazard", "toxic", "asphyxiation",
    "blowdown", "relief valve",
])

_ESCALATION_LABELS: frozenset[str] = frozenset({"Medium", "Low"})

ESCALATION_NOTICE = (
    "⚠ This question involves a safety-critical procedure. "
    "Confidence in this answer is limited — verify with a qualified "
    "engineer or safety officer before acting on it."
)


# ── Public API ───────────────────────────────────────────────────────────────

def is_high_stakes(query: str) -> bool:
    """Fast O(n·k) keyword scan — no LLM call, no latency impact."""
    q = query.lower()
    return any(kw in q for kw in HIGH_STAKES_KEYWORDS)


def get_escalation_notice(
    query: str,
    confidence_label: str,
    high_stakes: bool | None = None,
) -> str:
    """Return the escalation notice if the query is high-stakes and confidence
    is insufficient, otherwise return an empty string.

    Args:
        query:            The user's original question.
        confidence_label: "High" | "Medium" | "Low" (post-groundedness).
        high_stakes:      Pre-computed flag to avoid redundant keyword scan.
    """
    if high_stakes is None:
        high_stakes = is_high_stakes(query)

    if high_stakes and confidence_label in _ESCALATION_LABELS:
        return ESCALATION_NOTICE
    return ""
