"""
PII redactor — Section 4 of guardrails.

Regex-based redaction applied only at the display layer (citation excerpts
sent to the frontend). The underlying graph/vector store data is untouched.

Patterns:
  - Email addresses
  - Phone numbers (Indian + US formats)
  - Known person names (passed at call time from graph context)
"""
import re

# ─────────────────────────────────────────────────────────────────────────────
# Patterns
# ─────────────────────────────────────────────────────────────────────────────

EMAIL_PATTERN = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w{2,}", re.IGNORECASE)

# Covers: 123-456-7890, (123) 456-7890, +91 98765 43210, 9876543210, etc.
PHONE_PATTERN = re.compile(
    r"(\+?\d{1,3}[\s\-.]?)?"          # optional country code
    r"(\(?\d{2,4}\)?[\s\-.]?)"        # area code
    r"\d{3,4}[\s\-.]?\d{3,4}",        # local number
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def redact_pii(text: str, known_names: list[str] | None = None) -> str:
    """
    Redact PII from a text string. Applied to citation excerpts before
    they are sent to the frontend — raw data in the store is never modified.

    Args:
        text:         The citation excerpt text to redact.
        known_names:  Optional list of Person node names from the knowledge
                      graph to redact. Case-sensitive exact match.

    Returns:
        Redacted text with placeholders.
    """
    if not text:
        return text

    text = EMAIL_PATTERN.sub("[REDACTED EMAIL]", text)
    text = PHONE_PATTERN.sub("[REDACTED PHONE]", text)

    if known_names:
        for name in known_names:
            if name and len(name) > 2:  # Skip very short names — too risky to redact
                # Use word-boundary match to avoid partial replacements
                pattern = re.compile(r"\b" + re.escape(name) + r"\b")
                text = pattern.sub("[REDACTED NAME]", text)

    return text
