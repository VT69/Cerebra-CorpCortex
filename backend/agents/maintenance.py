"""
Maintenance & RCA Agent — fuses work order history, failure records,
OEM manuals, and inspection findings to generate maintenance recommendations.
Mohit owns this file.
"""
from backend.agents.base import BaseAgent, _context_to_str, _prior_outputs_to_str

SYSTEM_PROMPT = """
You are an expert maintenance engineer and Root Cause Analysis (RCA) specialist
for an industrial facility. You analyze maintenance history, failure patterns,
and equipment data to:
1. Generate predictive maintenance recommendations
2. Support Root Cause Analysis
3. Identify patterns that connect failures across time and equipment

When performing RCA, use the 5-Why methodology and reference specific failure records.
When making maintenance recommendations, cite:
- The failure pattern that triggered the recommendation
- The OEM guidance if available
- The time-since-last-maintenance
- Risk level: Critical / High / Medium / Low

Format for field use — be direct, actionable, and specific.
"""


class MaintenanceAgent(BaseAgent):
    async def run(self, question: str, context: list[dict], prior_outputs: list[dict]) -> dict:
        context_str = _context_to_str(context)
        prior_str = _prior_outputs_to_str(prior_outputs)

        user_prompt = f"""
Maintenance/RCA Question: {question}

{prior_str}

## Available maintenance records and equipment data:
{context_str}

Provide:
1. Direct answer to the question
2. If RCA is relevant: 5-Why analysis with evidence
3. Maintenance recommendations with priority (Critical/High/Medium/Low)
4. Cite specific work orders, inspection reports, or OEM manuals used
"""
        answer = await self._call_llm(SYSTEM_PROMPT, user_prompt)

        confidence = 0.80 if context else 0.45

        return {
            "answer": answer,
            "citations": self._build_citations(context),
            "confidence": confidence,
            "graph_path": [],
        }
