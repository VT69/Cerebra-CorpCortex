"""
Regex PII redaction for everything that leaves the backend or is persisted
in logs: API answers, supporting detail, groundedness warnings, citation
excerpts, reviewer views and audit records.

The vector store and graph keep raw text (so retrieval still works); PII
there is protected by access control, not redaction. Names are NOT detected
by regex — that needs NER (see known gaps).
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

# Phone numbers. Each alternative consumes the whole number so no digit is
# left behind (v1 turned "+91 98765 43210" into "[REDACTED PHONE]0").
#   - international: "+" country code, then 7-12 digits with optional separators
#   - parenthesised area code: "(022) 2345 6789"
#   - Indian mobile without country code: starts 6-9, 10 digits ("98765 43210").
#     The 6-9 lead digit keeps part numbers like "12345-67890" out.
PHONE_INTL_PATTERN = re.compile(r"\+\d{1,3}(?:[\s.()\-]{0,2}\d){7,12}\b")
PHONE_PATTERN = re.compile(
    r"(?:"
    r"\(\d{2,4}\)[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}\b"
    r"|"
    r"\b[6-9]\d{4}[\s\-.]?\d{5}\b"
    r")",
)

# Indian Aadhaar: 12 digits, spaced, hyphenated or contiguous
# (1234 5678 9012 / 1234-5678-9012 / 123456789012).
AADHAAR_PATTERN = re.compile(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b")

# Indian PAN: 5 letters + 4 digits + 1 letter, any case (ABCDE1234F / abcde1234f).
PAN_PATTERN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.IGNORECASE)


# ── Public API ───────────────────────────────────────────────────────────────

def redact_pii(text: str, known_names: list[str] | None = None) -> str:
    """Redact PII from a citation excerpt before sending to the frontend.

    Applies regex-based redaction for emails, phone numbers, Aadhaar,
    and PAN. Optionally redacts known person names from the knowledge graph.
    """
    if not text:
        return text

    # Order matters: international phones first (so "+91..." is not half-read
    # as an Aadhaar), then Aadhaar before the 10-digit mobile pattern.
    text = EMAIL_PATTERN.sub("[REDACTED EMAIL]", text)
    text = PHONE_INTL_PATTERN.sub("[REDACTED PHONE]", text)
    text = AADHAAR_PATTERN.sub("[REDACTED AADHAAR]", text)
    text = PAN_PATTERN.sub("[REDACTED PAN]", text)
    text = PHONE_PATTERN.sub("[REDACTED PHONE]", text)

    if known_names:
        for name in known_names:
            if name and len(name) >= settings.PII_MIN_NAME_LENGTH:
                pattern = re.compile(r"\b" + re.escape(name) + r"\b")
                text = pattern.sub("[REDACTED NAME]", text)

    return text


def redact_obj(value):
    """Recursively redact strings inside dicts/lists (for log records and API payloads)."""
    if isinstance(value, str):
        return redact_pii(value)
    if isinstance(value, list):
        return [redact_obj(v) for v in value]
    if isinstance(value, dict):
        return {k: redact_obj(v) for k, v in value.items()}
    return value
