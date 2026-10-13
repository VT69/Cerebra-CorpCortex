"""
Copilot Agent — general Q&A across the full document corpus.
Mohit owns this file.

Updated: outputs structured JSON directly so supervisor.py can skip the
redundant _structured_synthesize LLM call and stay fast.
"""
import json
from backend.agents.base import BaseAgent, _context_to_str, _prior_outputs_to_str, compute_confidence

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

        # Confidence from retrieval strength, same function as every agent
        # (more reliable than asking the LLM to rate itself)
        confidence = compute_confidence(context)

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


# Backwards-compatible alias; the implementation lives in base.compute_confidence.
_score_confidence = compute_confidence
