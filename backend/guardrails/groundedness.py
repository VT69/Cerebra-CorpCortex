"""
Independent post-synthesis groundedness verification.

A second LLM pass fact-checks each claim in the generated answer against
retrieved context, preventing the synthesizing model from being the sole
arbiter of its own confidence ("grading its own homework").

Confidence is capped deterministically based on the ratio of unsupported
claims — see ``apply_groundedness_to_confidence`` for the cap rules.
"""

import json
import logging
from typing import TypedDict

from openai import AsyncOpenAI

from backend.config import settings

logger = logging.getLogger(__name__)

_oai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


# ── Return types ─────────────────────────────────────────────────────────────

class ClaimVerdict(TypedDict):
    claim: str
    status: str  # "supported" | "partial" | "unsupported"


class GroundednessResult(TypedDict, total=False):
    claims: list[ClaimVerdict]
    overall_grounded: bool
    unsupported_claims: list[str]
    skipped: bool
    error: str


# ── Verification prompt ──────────────────────────────────────────────────────

_VERIFICATION_PROMPT = """\
You are a strict fact-checker. Given an ANSWER and the CONTEXT it was \
generated from, classify each factual claim as:
- "supported"   — directly stated or clearly implied by the CONTEXT
- "partial"     — loosely related but not directly stated
- "unsupported" — not present in the CONTEXT at all

ANSWER:
{answer}

CONTEXT:
{context}

Return strict JSON only:
{{
  "claims": [{{"claim": "<text>", "status": "supported|partial|unsupported"}}],
  "overall_grounded": <true only if ALL claims are "supported">,
  "unsupported_claims": ["<any partial or unsupported claim text>"]
}}"""


# ── Public API ───────────────────────────────────────────────────────────────

_SKIP_QUERY_TYPES = frozenset({"small_talk", "off-topic"})

_SKIPPED_RESULT: GroundednessResult = {
    "claims": [],
    "overall_grounded": True,
    "unsupported_claims": [],
    "skipped": True,
}


async def verify_groundedness(
    answer: str,
    context_chunks: list[str],
    query_type: str = "single-fact",
) -> GroundednessResult:
    """Run an independent groundedness check on the generated answer.

    Short-circuits for small_talk / off-topic queries where there is no
    retrieved context to verify against (no LLM cost incurred).
    """
    if query_type in _SKIP_QUERY_TYPES or not context_chunks or not answer:
        return _SKIPPED_RESULT

    context_text = "\n---\n".join(c for c in context_chunks if c.strip())
    prompt = _VERIFICATION_PROMPT.format(answer=answer, context=context_text)

    try:
        response = await _oai.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a strict fact-checker. Return JSON only."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        result = json.loads(response.choices[0].message.content)
        result["skipped"] = False
        return result
    except Exception:
        # Fail-open: don't block the response if verification errors out.
        logger.exception("Groundedness verification failed — defaulting to grounded")
        return {**_SKIPPED_RESULT, "error": "verification_failed"}


def apply_groundedness_to_confidence(
    groundedness: GroundednessResult,
    current_confidence: float,
    current_label: str,
) -> tuple[float, str, list[str]]:
    """Adjust confidence based on groundedness verification.

    Cap rules (thresholds from ``settings``):
      - All claims supported       → no change
      - Any partial/unsupported    → cap at Medium (GROUNDEDNESS_CAP_PARTIAL)
      - >UNSUPPORTED_RATIO claims  → cap at Low   (GROUNDEDNESS_CAP_LOW)

    Returns:
        (adjusted_confidence, adjusted_label, list_of_unsupported_claims)
    """
    if groundedness.get("skipped") or groundedness.get("overall_grounded"):
        return current_confidence, current_label, []

    unsupported = groundedness.get("unsupported_claims", [])
    total_claims = len(groundedness.get("claims", []))
    unsupported_count = len(unsupported)

    if total_claims > 0 and unsupported_count / total_claims > settings.GROUNDEDNESS_UNSUPPORTED_RATIO:
        new_confidence = min(current_confidence, settings.GROUNDEDNESS_CAP_LOW)
        new_label = "Low"
    else:
        new_confidence = min(current_confidence, settings.GROUNDEDNESS_CAP_PARTIAL)
        new_label = "Medium" if current_label == "High" else current_label

    return round(new_confidence, 3), new_label, unsupported
