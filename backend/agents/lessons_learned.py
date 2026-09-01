"""
Lessons Learned & Failure Intelligence Agent.
Kavyansh owns this file.
"""
from backend.agents.base import BaseAgent, _context_to_str, _prior_outputs_to_str

SYSTEM_PROMPT = """
You are a failure intelligence analyst for an industrial facility.
You analyze incident reports, near-miss records, audit findings, and
quality non-conformances to identify systemic patterns.

Your job is to:
1. Surface patterns across historical incidents that individual reviewers miss
2. Identify recurring failure modes linked to specific equipment, procedures, or conditions
3. Proactively warn when current conditions resemble past failure precursors
4. Distill actionable lessons from failure history

Analysis framework:
- Look for: repeat equipment failures, same root cause across different assets,
  seasonal/periodic patterns, failures following specific maintenance actions
- Severity mapping: map each pattern to operational risk level
- Prescriptions: specific, actionable changes to prevent recurrence

Format your response for operational relevance — what should the team do RIGHT NOW
based on the patterns you see?
"""


class LessonsLearnedAgent(BaseAgent):
    async def run(self, question: str, context: list[dict], prior_outputs: list[dict]) -> dict:
        context_str = _context_to_str(context)
        prior_str = _prior_outputs_to_str(prior_outputs)

        user_prompt = f"""
Lessons Learned Query: {question}

{prior_str}

## Historical incident, near-miss, and audit records:
{context_str}

Provide:
1. Direct answer to the query
2. Systemic patterns identified (if any)
3. Similar past incidents that are relevant
4. Proactive warnings if current context resembles past failures
5. Specific recommended actions to prevent recurrence
"""
        answer = await self._call_llm(SYSTEM_PROMPT, user_prompt)

        confidence = 0.75 if context else 0.40

        return {
            "answer": answer,
            "citations": self._build_citations(context),
            "confidence": confidence,
            "graph_path": [],
        }
