"""
Two-pass LLM extraction pipeline.
Pass 1: LLM proposes entities and relationships from document chunk.
Pass 2: Verifier checks against ontology + existing graph, assigns confidence.
Only verified facts (confidence >= threshold) get written to the graph.

Vaibhav owns this file.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI
from backend.shared.ontology import NODE_TYPES, EDGE_TYPES, Provenance, CONFIDENCE_THRESHOLDS
from backend.config import settings

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# ─────────────────────────────────────────────────────────────────────────────
# PASS 1 — Extraction Prompt (Pinned System Prompt — do not modify without team)
# ─────────────────────────────────────────────────────────────────────────────

EXTRACTION_SYSTEM_PROMPT = """
You are an industrial knowledge extraction engine for an oil & gas / manufacturing facility.
Extract structured facts from the provided text following the STRICT ontology below.

## Ontology

### Node Types (ONLY these 6 — no others):
- Equipment: Physical assets (tag, name, type, location, manufacturer, model)
- Document: Source documents (title, doc_type, doc_number, date, revision)
- Parameter: Process parameters (name, value, unit, design_value, operating_value)
- Person: Personnel (name, role, employee_id, department)
- Regulation: Regulatory references (code, title, section, authority)
- Event: Time-bound events (type, date, description, severity)

### Edge Types (ONLY these 8):
- HAS_PARAMETER: Equipment → Parameter
- DOCUMENTED_IN: Equipment/Event/Parameter → Document
- PERFORMED_BY: Event → Person
- PRECEDED_BY: Event → Event
- REGULATED_BY: Equipment/Process → Regulation
- CONNECTED_TO: Equipment → Equipment
- MENTIONS: Document → Equipment/Person/Regulation
- CAUSED_BY: Event → Equipment/Parameter

## Output Format
Return ONLY valid JSON matching this schema exactly:
{
  "nodes": [
    {"type": "Equipment", "id": "unique-stable-id", "properties": {...}, "text_span": "exact quote from source"}
  ],
  "edges": [
    {"from_id": "id1", "from_type": "Equipment", "edge_type": "HAS_PARAMETER", "to_id": "id2", "to_type": "Parameter", "text_span": "quote"}
  ]
}

## Rules
- IDs must be stable and unique within the document (e.g. "pump-P-101", "event-2024-03-15-failure")
- Only extract facts explicitly stated in the text — no inference
- Include the exact text_span that justifies each extraction
- Equipment tags must follow the format found in the text (e.g. "P-101", "V-201")
"""

# ─────────────────────────────────────────────────────────────────────────────
# PASS 2 — Verification Prompt
# ─────────────────────────────────────────────────────────────────────────────

VERIFIER_SYSTEM_PROMPT = """
You are an ontology verifier for an industrial knowledge graph.
You receive proposed facts from an extraction pass and must:
1. Verify each node/edge conforms to the ontology schema
2. Assign a confidence score (0.0 - 1.0) based on:
   - Text evidence quality (explicit statement vs. implied)
   - Node type correctness
   - ID consistency and stability
   - Completeness of required fields
3. Flag any violations

Return ONLY valid JSON:
{
  "verified_nodes": [
    {"id": "...", "confidence": 0.95, "violations": [], "approved": true}
  ],
  "verified_edges": [
    {"from_id": "...", "to_id": "...", "edge_type": "...", "confidence": 0.88, "violations": [], "approved": true}
  ]
}

Confidence scoring guide:
- 0.90-1.0: Explicit, unambiguous statement with exact text evidence
- 0.70-0.89: Clear statement, minor ambiguity
- 0.50-0.69: Implied or inferred (DO NOT write to graph if < 0.70)
- Below 0.50: Uncertain — reject
"""


class TwoPassExtractor:
    """
    Extracts industrial knowledge from document chunks using a two-pass LLM approach.
    """

    def __init__(self):
        self.pass_id = str(uuid.uuid4())
        self.extracted_at = datetime.now(timezone.utc).isoformat()

    async def extract(
        self,
        text: str,
        source_doc_id: str,
        doc_type: str = "generic",
    ) -> dict[str, list]:
        """
        Run Pass 1 (extraction) + Pass 2 (verification).
        Returns only approved nodes and edges with provenance.
        """
        # Pass 1: Extract
        raw = await self._pass1_extract(text, doc_type)
        if not raw:
            return {"nodes": [], "edges": []}

        # Pass 2: Verify
        verified = await self._pass2_verify(raw, text)

        # Merge: attach provenance to approved facts
        return self._merge_with_provenance(raw, verified, source_doc_id)

    async def _pass1_extract(self, text: str, doc_type: str) -> dict:
        """Call LLM to extract raw facts."""
        try:
            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Document type: {doc_type}\n\n---\n\n{text}"},
                ],
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            print(f"[Extractor] Pass 1 failed: {e}")
            return {}

    async def _pass2_verify(self, raw_facts: dict, original_text: str) -> dict:
        """Call LLM verifier to score and approve facts."""
        try:
            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Original text:\n{original_text}\n\n"
                            f"Proposed facts:\n{json.dumps(raw_facts, indent=2)}"
                        ),
                    },
                ],
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            print(f"[Extractor] Pass 2 failed: {e}")
            return {}

    def _merge_with_provenance(
        self,
        raw: dict,
        verified: dict,
        source_doc_id: str,
    ) -> dict:
        """
        Combine raw facts with verification results.
        Only include facts that are approved AND meet confidence threshold.
        """
        approved_node_ids = {
            v["id"]: v
            for v in verified.get("verified_nodes", [])
            if v.get("approved") and v.get("confidence", 0) >= CONFIDENCE_THRESHOLDS["write_to_graph"]
        }
        approved_edges = {
            (v["from_id"], v["to_id"], v["edge_type"]): v
            for v in verified.get("verified_edges", [])
            if v.get("approved") and v.get("confidence", 0) >= CONFIDENCE_THRESHOLDS["write_to_graph"]
        }

        nodes_out = []
        for node in raw.get("nodes", []):
            if node["id"] in approved_node_ids:
                v = approved_node_ids[node["id"]]
                prov = Provenance(
                    source_doc_id=source_doc_id,
                    confidence=v["confidence"],
                    extraction_pass_id=self.pass_id,
                    extracted_at=self.extracted_at,
                    extracted_by=f"{settings.OPENAI_MODEL}-two-pass",
                    verified=True,
                    raw_text_span=node.get("text_span"),
                )
                nodes_out.append({"node": node, "provenance": prov})

        edges_out = []
        for edge in raw.get("edges", []):
            key = (edge["from_id"], edge["to_id"], edge["edge_type"])
            if key in approved_edges:
                v = approved_edges[key]
                prov = Provenance(
                    source_doc_id=source_doc_id,
                    confidence=v["confidence"],
                    extraction_pass_id=self.pass_id,
                    extracted_at=self.extracted_at,
                    extracted_by=f"{settings.OPENAI_MODEL}-two-pass",
                    verified=True,
                    raw_text_span=edge.get("text_span"),
                )
                edges_out.append({"edge": edge, "provenance": prov})

        return {"nodes": nodes_out, "edges": edges_out}
