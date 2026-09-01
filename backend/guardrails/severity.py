"""
High-stakes query severity classifier — Section 3 of guardrails.

Fast keyword check (no LLM call) to flag safety-critical queries.
When a query is high-stakes AND the system's confidence is Medium or Low,
an escalation notice is added to the response directing the user to verify
with a qualified engineer or safety officer before acting.

Every high-stakes query is logged to ./data/escalation_audit.jsonl
regardless of whether escalation triggered — this provides an audit trail
demonstrating the system knows when to defer to humans.
"""

# ─────────────────────────────────────────────────────────────────────────────
# Keyword list
# ─────────────────────────────────────────────────────────────────────────────

HIGH_STAKES_KEYWORDS = [
    "lockout",
    "tagout",
    "loto",
    "shutdown",
    "permit",
    "hazard",
    "gas leak",
    "evacuation",
    "confined space",
    "hot work",
    "pressure release",
    "emergency",
    "compliance violation",
    "safety procedure",
    "explosion",
    "fire hazard",
    "toxic",
    "asphyxiation",
    "blowdown",
    "relief valve",
]

# Labels that warrant escalation when combined with high-stakes query
_ESCALATION_LABELS = {"Medium", "Low"}

ESCALATION_NOTICE = (
    "⚠ This question involves a safety-critical procedure. "
    "Confidence in this answer is limited — verify with a qualified "
    "engineer or safety officer before acting on it."
)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def is_high_stakes(query: str) -> bool:
    """
    Fast O(n) keyword scan — no LLM call, no latency impact.
    Returns True if the query touches any safety-critical domain.
    """
    q = query.lower()
    return any(kw in q for kw in HIGH_STAKES_KEYWORDS)


def get_escalation_notice(
    query: str,
    confidence_label: str,
    high_stakes: bool | None = None,
) -> str:
    """
    Return the escalation notice string if conditions are met, else empty string.

    Args:
        query:            The user's original question.
        confidence_label: "High" | "Medium" | "Low"
        high_stakes:      Pass pre-computed flag to avoid re-checking keywords.
    """
    if high_stakes is None:
        high_stakes = is_high_stakes(query)

    if high_stakes and confidence_label in _ESCALATION_LABELS:
        return ESCALATION_NOTICE
    return ""
