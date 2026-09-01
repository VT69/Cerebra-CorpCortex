"""
Copilot Agent — general Q&A across the full document corpus.
Mohit owns this file.

Updated: outputs structured JSON directly so supervisor.py can skip the
redundant _structured_synthesize LLM call and stay fast.
"""
import json
from backend.agents.base import BaseAgent, _context_to_str, _prior_outputs_to_str

SYSTEM_PROMPT = """\
You are an industrial knowledge copilot for a manufacturing/oil & gas facility.
Answer operational, maintenance, and engineering questions accurately, citing specific source documents.

You MUST respond with ONLY a valid JSON object — no text outside the JSON.

Schema:
{
  "answer": "<direct, clear answer in 1-3 sentences — field technicians need fast, clear answers>",
  "supporting_detail": "<one or two sentences of additional context, or empty string>",
  "citation_note": "<e.g. 'OSHA 29 CFR 1910.147, Section (c)(4)' or document name + section>"
}

Rules:
- Answer directly using the retrieved context
- If the context fully covers the answer, be specific and confident
- If context is partial, still provide the best answer but note limitations in supporting_detail
- Use technical terminology appropriate for industrial operations
"""


class CopilotAgent(BaseAgent):
    async def run(self, question: str, context: list[dict], prior_outputs: list[dict]) -> dict:
        context_str = _context_to_str(context)
        prior_str = _prior_outputs_to_str(prior_outputs)

        user_prompt = f"""Question: {question}

{prior_str}

## Retrieved knowledge base excerpts:
{context_str}

Provide a clear, accurate answer based on the excerpts above."""

        raw = await self._call_llm(SYSTEM_PROMPT, user_prompt)

        # Try to parse structured JSON output
        structured = {}
        try:
            structured = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            # Graceful fallback — use raw text as answer
            structured = {
                "answer": raw,
                "supporting_detail": "",
                "citation_note": "",
            }

        answer = structured.get("answer") or raw
        supporting_detail = structured.get("supporting_detail", "")
        citation_note = structured.get("citation_note", "")

        # Compute confidence deterministically from vector similarity scores
        # (more reliable than asking the LLM to rate itself)
        confidence = _score_confidence(context)

        return {
            "answer": answer,
            "supporting_detail": supporting_detail,
            "citation_note": citation_note,
            "citations": self._build_citations(context),
            "confidence": confidence,
            "graph_path": [
                hop
                for item in context
                if item.get("source") == "graph"
                for hop in item.get("graph_path", [])
            ],
        }


def _score_confidence(context: list[dict]) -> float:
    """
    Compute answer confidence deterministically from retrieval scores.
    
    Thresholds calibrated for cosine similarity scores from sentence-transformers:
    - High  (≥ 0.72): Top result is strongly relevant — context clearly covers the question
    - Medium(≥ 0.52): Partial or indirect relevance
    - Low   (< 0.52): Weak retrieval — answer may be unreliable
    """
    if not context:
        return 0.0

    top_score = max((item.get("final_score", 0) for item in context), default=0.0)

    if top_score >= 0.72:
        return round(0.85 + min(0.14, (top_score - 0.72) * 0.5), 3)   # 0.85–0.99
    elif top_score >= 0.52:
        # Scale 0.52–0.72 → 0.60–0.84
        scaled = 0.60 + (top_score - 0.52) / 0.20 * 0.24
        return round(min(0.84, scaled), 3)
    else:
        # Scale 0–0.52 → 0.10–0.59
        scaled = 0.10 + top_score / 0.52 * 0.49
        return round(min(0.59, scaled), 3)
