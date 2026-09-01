"""
Compliance Agent — maps regulations against current procedures and equipment states.
Kavyansh owns this file.
"""
from backend.agents.base import BaseAgent, _context_to_str, _prior_outputs_to_str

SYSTEM_PROMPT = """
You are a regulatory compliance specialist for Indian heavy industry.
You have deep knowledge of:
- OISD (Oil Industry Safety Directorate) standards
- PESO (Petroleum and Explosives Safety Organisation) regulations
- Factory Act and Rules
- Environmental norms (Environment Protection Act, CPCB guidelines)
- BIS quality standards

Your job is to:
1. Identify compliance gaps between current procedures/equipment and regulatory requirements
2. Generate compliance evidence packages for audits
3. Flag quality deviations and safety non-conformances
4. Reference specific regulation sections (e.g. "OISD-118 Clause 4.2.3")

Always:
- Cite the exact regulation section number
- State gap severity: Critical (immediate action) / Major / Minor / Observation
- Suggest specific corrective actions
- Indicate if documentation is missing vs procedure gap vs equipment gap
"""


class ComplianceAgent(BaseAgent):
    async def run(self, question: str, context: list[dict], prior_outputs: list[dict]) -> dict:
        context_str = _context_to_str(context)
        prior_str = _prior_outputs_to_str(prior_outputs)

        user_prompt = f"""
Compliance Question: {question}

{prior_str}

## Current procedures, equipment records, and regulatory documents:
{context_str}

Provide:
1. Compliance status (Compliant / Non-Compliant / Partially Compliant / Insufficient Data)
2. Specific gaps found with regulation references
3. Gap severity for each finding
4. Recommended corrective actions
5. Documents needed for audit evidence package
"""
        answer = await self._call_llm(SYSTEM_PROMPT, user_prompt)

        confidence = 0.78 if context else 0.40

        return {
            "answer": answer,
            "citations": self._build_citations(context),
            "confidence": confidence,
            "graph_path": [],
        }
