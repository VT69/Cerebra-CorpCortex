"""
Neo4j graph traversal for multi-hop and aggregation queries.
Mohit owns this file.
"""
import json
from neo4j import AsyncDriver
from openai import AsyncOpenAI
from backend.config import settings
from backend.graph.writer import get_driver

_oai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# ─────────────────────────────────────────────────────────────────────────────
# Cypher Generation Prompt
# ─────────────────────────────────────────────────────────────────────────────

CYPHER_GEN_PROMPT = """
You are a Neo4j Cypher query generator for an industrial knowledge graph.

## Graph Schema
Nodes: Equipment, Document, Parameter, Person, Regulation, Event
Edge types: HAS_PARAMETER, DOCUMENTED_IN, PERFORMED_BY, PRECEDED_BY,
            REGULATED_BY, CONNECTED_TO, MENTIONS, CAUSED_BY

All nodes have: id, role_tag, last_updated
Equipment: tag, name, type, location, manufacturer, model
Event: type, date, description, severity
Parameter: name, value, unit, design_value, operating_value
Person: name, role, employee_id, department
Regulation: code, title, section, authority
Document: title, doc_type, doc_number, date, revision

All edges have: source_doc_id, confidence, extraction_pass_id, extracted_at, verified

## Rules
- Always limit results: LIMIT 20
- Only traverse up to {hop_limit} hops
- Filter on verified=true for edges unless told otherwise
- Return node properties AND the path for citations
- If unsure, prefer a broader query over a narrow one

Return ONLY a valid Cypher query string, no explanation.
"""


async def graph_search(
    query: str,
    query_type: str = "multi-hop",
    hop_limit: int = None,
) -> list[dict]:
    """
    Generate and run a Cypher query for the given natural language question.
    Returns list of {node_id, node_type, properties, graph_path, source_docs}.
    """
    hop_limit = hop_limit or settings.GRAPH_HOP_LIMIT

    # Generate Cypher from natural language
    cypher = await _generate_cypher(query, query_type, hop_limit)
    if not cypher:
        return []

    # Execute against Neo4j
    try:
        driver = await get_driver()
        results = await _run_cypher(driver, cypher)
        await driver.close()
        return results
    except Exception as e:
        print(f"[GraphSearch] Neo4j unavailable or Cypher failed: {e}")
        return []


async def _generate_cypher(query: str, query_type: str, hop_limit: int) -> str:
    """Use LLM to translate NL question → Cypher."""
    try:
        response = await _oai.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": CYPHER_GEN_PROMPT.format(hop_limit=hop_limit),
                },
                {
                    "role": "user",
                    "content": f"Query type: {query_type}\nQuestion: {query}",
                },
            ],
            temperature=0.0,
            max_tokens=500,
        )
        cypher = response.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if cypher.startswith("```"):
            cypher = cypher.split("```")[1]
            if cypher.startswith("cypher"):
                cypher = cypher[6:]
        return cypher.strip()
    except Exception as e:
        print(f"[GraphSearch] Cypher generation failed: {e}")
        return ""


async def _run_cypher(driver: AsyncDriver, cypher: str) -> list[dict]:
    """Execute Cypher and return structured results."""
    results = []
    async with driver.session() as session:
        cursor = await session.run(cypher)
        records = await cursor.data()
        for record in records:
            # Flatten record into a dict, collect source_doc_ids for citations
            flat = {}
            source_docs = []
            graph_path = []
            for key, value in record.items():
                if hasattr(value, "items"):  # Neo4j Node
                    flat[key] = dict(value)
                    graph_path.append({
                        "node_id": value.get("id", ""),
                        "node_type": list(value.labels)[0] if hasattr(value, "labels") else "Unknown",
                        "label": value.get("name") or value.get("tag") or value.get("id", ""),
                    })
                    if "source_doc_id" in value:
                        source_docs.append(value["source_doc_id"])
                else:
                    flat[key] = value
            results.append({
                "properties": flat,
                "graph_path": graph_path,
                "source_docs": list(set(source_docs)),
            })
    return results
