"""
Display-layer PII redaction for citation excerpts.

Applied only to text shown in the frontend — the underlying vector store
and graph data are never modified. This ensures the raw data remains
searchable while preventing PII leakage in user-facing responses.
"""

import logging
import re

from backend.config import settings

logger = logging.getLogger(__name__)


# ── Patterns ─────────────────────────────────────────────────────────────────

EMAIL_PATTERN = re.compile(
    r"\b[\w.\-+]+@[\w.\-]+\.\w{2,}\b",
    re.IGNORECASE,
)

# Requires a country code (+XX), parenthesized area code, or 10-digit Indian
# mobile format. Anchored to reduce false positives on part/serial numbers.
PHONE_PATTERN = re.compile(
    r"(?:"
    r"\+\d{1,3}[\s\-.]?\(?\d{2,4}\)?[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}"
    r"|"
    r"\(\d{2,4}\)[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}"
    r"|"
    r"\b\d{5}[\s\-.]?\d{5}\b"
    r")",
)

# Indian Aadhaar: 12 digits in groups of 4 (e.g. 1234 5678 9012)
AADHAAR_PATTERN = re.compile(r"\b\d{4}[\s\-]\d{4}[\s\-]\d{4}\b")

# Indian PAN: 5 letters + 4 digits + 1 letter (e.g. ABCDE1234F)
PAN_PATTERN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")


# ── Public API ───────────────────────────────────────────────────────────────

def redact_pii(text: str, known_names: list[str] | None = None) -> str:
    """Redact PII from a citation excerpt before sending to the frontend.

    Applies regex-based redaction for emails, phone numbers, Aadhaar,
    and PAN. Optionally redacts known person names from the knowledge graph.
    """
    if not text:
        return text

    text = EMAIL_PATTERN.sub("[REDACTED EMAIL]", text)
    text = PHONE_PATTERN.sub("[REDACTED PHONE]", text)
    text = AADHAAR_PATTERN.sub("[REDACTED AADHAAR]", text)
    text = PAN_PATTERN.sub("[REDACTED PAN]", text)

    if known_names:
        for name in known_names:
            if name and len(name) >= settings.PII_MIN_NAME_LENGTH:
                pattern = re.compile(r"\b" + re.escape(name) + r"\b")
                text = pattern.sub("[REDACTED NAME]", text)

    return text
