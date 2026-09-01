"""
Query classifier — determines retrieval strategy for each incoming question.
Mohit owns this file.

Query types:
  - single-fact: "What is the design pressure of vessel V-201?"
  - multi-hop: "What failures has pump P-101 had after maintenance by John Kumar?"
  - aggregation: "How many unplanned shutdowns occurred in Q1 2024?"
"""
import json
from openai import AsyncOpenAI
from backend.config import settings

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

CLASSIFIER_PROMPT = """
You are a query classifier for an industrial knowledge system.
Classify the user's question into exactly one of three types:

- single-fact: Can be answered from a single document or node lookup.
  Examples: equipment specs, a specific parameter value, who performed an inspection.

- multi-hop: Requires joining information across multiple entities/documents.
  Examples: failure history of equipment maintained by a specific person,
  compliance status of equipment linked to a specific regulation.

- aggregation: Requires counting, averaging, or summarizing across many records.
  Examples: number of incidents per equipment type, average MTBF, trend analysis.

- off-topic: The query is completely unrelated to industrial safety, maintenance, compliance, or the manufacturing domain.
  Examples: "What is the capital of France?", "Write a poem", "How to bake a cake".

Return ONLY valid JSON:
{"query_type": "single-fact" | "multi-hop" | "aggregation" | "off-topic", "reasoning": "one sentence"}
"""

async def classify_query(question: str) -> dict:
    """
    Returns {"query_type": str, "reasoning": str}
    Falls back to "multi-hop" on any error (safe default).
    """
    try:
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": CLASSIFIER_PROMPT},
                {"role": "user", "content": question},
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"[Classifier] Failed: {e} — defaulting to multi-hop")
        return {"query_type": "multi-hop", "reasoning": "classification failed, using safe default"}
