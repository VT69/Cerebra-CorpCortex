"""
Groundedness verifier — Section 1 of guardrails.

Independent post-synthesis fact-check: a second LLM pass verifies each
factual claim in the generated answer against the retrieved context.
This prevents self-rated confidence from being the only safety signal
(the model grading its own homework problem).

Short-circuits immediately for small_talk / off-topic queries (no context
to check → no cost incurred).
"""
import json
from openai import AsyncOpenAI
from backend.config import settings

_oai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# ─────────────────────────────────────────────────────────────────────────────
# Prompt
# ─────────────────────────────────────────────────────────────────────────────

GROUNDEDNESS_PROMPT = """
You are a strict fact-checker. You will be given an ANSWER and the CONTEXT
it was supposedly generated from. Your job is ONLY to check grounding —
do not evaluate helpfulness or writing style.

ANSWER:
{answer}

CONTEXT (retrieved documents / graph facts):
{context}

For each factual claim in the ANSWER, determine if it is:
- "supported"   : directly stated or clearly implied by the CONTEXT
- "partial"     : loosely related but not directly stated
- "unsupported" : not present in the CONTEXT at all

Return strict JSON only — no commentary outside the JSON:
{{
  "claims": [
    {{"claim": "<claim text>", "status": "supported|partial|unsupported"}}
  ],
  "overall_grounded": <true only if ALL claims are "supported">,
  "unsupported_claims": ["<list of any partial or unsupported claim text>"]
}}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def verify_groundedness(
    answer: str,
    context_chunks: list[str],
    query_type: str = "single-fact",
) -> dict:
    """
    Run an independent groundedness check on the generated answer.

    Args:
        answer:         The final answer text produced by the synthesis step.
        context_chunks: List of raw text strings from retrieved context items.
        query_type:     If "small_talk" or "off-topic", short-circuits with a
                        fully-grounded result (no LLM call, no cost).

    Returns:
        {
          "claims": [...],
          "overall_grounded": bool,
          "unsupported_claims": [...],
          "skipped": bool   # True when short-circuited
        }
    """
    # Short-circuit for queries that have no retrieved context
    if query_type in ("small_talk", "off-topic") or not context_chunks or not answer:
        return {
            "claims": [],
            "overall_grounded": True,
            "unsupported_claims": [],
            "skipped": True,
        }

    context_text = "\n---\n".join(c for c in context_chunks if c.strip())

    prompt = GROUNDEDNESS_PROMPT.format(answer=answer, context=context_text)

    try:
        response = await _oai.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a strict fact-checker. Return JSON only."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,  # deterministic
        )
        result = json.loads(response.choices[0].message.content)
        result["skipped"] = False
        return result
    except Exception as e:
        print(f"[Groundedness] Verification failed: {e}")
        # On failure, return a safe default — don't block the response
        return {
            "claims": [],
            "overall_grounded": True,
            "unsupported_claims": [],
            "skipped": True,
            "error": str(e),
        }


def apply_groundedness_to_confidence(
    groundedness: dict,
    current_confidence: float,
    current_label: str,
) -> tuple[float, str, list[str]]:
    """
    Adjust confidence score and label based on groundedness result.

    Rules:
      - All supported → keep original confidence + label unchanged
      - Any partial/unsupported → cap at Medium (max 0.75)
      - >50% unsupported claims → cap at Low (max 0.40)

    Returns:
        (adjusted_confidence, adjusted_label, groundedness_warning)
    """
    if groundedness.get("skipped") or groundedness.get("overall_grounded"):
        return current_confidence, current_label, []

    unsupported = groundedness.get("unsupported_claims", [])
    total_claims = len(groundedness.get("claims", []))
    unsupported_count = len(unsupported)

    if total_claims > 0 and unsupported_count / total_claims > 0.5:
        # More than half the claims unsupported → cap at Low
        new_confidence = min(current_confidence, 0.40)
        new_label = "Low"
    else:
        # Some unsupported → cap at Medium
        new_confidence = min(current_confidence, 0.75)
        new_label = "Medium" if current_label == "High" else current_label

    return round(new_confidence, 3), new_label, unsupported
