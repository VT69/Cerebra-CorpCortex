"""
Shared contract: 6-node/edge ontology for the Industrial Knowledge Graph.
Both Vaibhav (storage) and Mohit (retrieval) depend on this file.
Do not change without team agreement.
"""
from dataclasses import dataclass, field
from typing import Literal, Optional
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# Node Types (6 canonical types)
# ─────────────────────────────────────────────────────────────────────────────

NODE_TYPES = Literal[
    "Equipment",        # Physical assets — pumps, vessels, compressors, valves
    "Document",         # Source document — P&ID, work order, SOP, report
    "Parameter",        # Process parameters — pressure, temperature, flow rate
    "Person",           # Personnel — operator, engineer, inspector
    "Regulation",       # Regulatory references — OISD-118, Factory Act S.7A
    "Event",            # Time-bound events — failure, inspection, incident, shutdown
]

# ─────────────────────────────────────────────────────────────────────────────
# Edge Types (8 canonical relationship types)
# ─────────────────────────────────────────────────────────────────────────────

EDGE_TYPES = Literal[
    "HAS_PARAMETER",        # Equipment → Parameter
    "DOCUMENTED_IN",        # Equipment/Event/Parameter → Document
    "PERFORMED_BY",         # Event → Person
    "PRECEDED_BY",          # Event → Event (causal / temporal chain)
    "REGULATED_BY",         # Equipment/Process → Regulation
    "CONNECTED_TO",         # Equipment → Equipment (P&ID connectivity)
    "MENTIONS",             # Document → Equipment/Person/Regulation
    "CAUSED_BY",            # Event → Equipment/Parameter (RCA link)
]

# ─────────────────────────────────────────────────────────────────────────────
# Provenance / Confidence Field Format
# Agreed contract: EVERY edge in the graph carries this payload
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Provenance:
    source_doc_id: str              # Document node ID that generated this fact
    confidence: float               # 0.0 - 1.0, set by verifier
    extraction_pass_id: str         # UUID of the extraction run
    extracted_at: str               # ISO 8601 timestamp
    extracted_by: str               # Model/agent that extracted (e.g. "gpt-4o-pass1")
    verified: bool                  # True only after verifier pass
    role_tag: str = "general"       # "general" | "safety-officer-only" | "admin-only"
    raw_text_span: Optional[str] = None   # Source text that produced this fact (for citations)

# ─────────────────────────────────────────────────────────────────────────────
# API Response Contract
# Shape of every answer returned by the supervisor agent
# Both frontend (Kavyansh) and agents (Mohit) depend on this
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AgentResponse:
    answer: str                         # Natural language answer
    citations: list[dict]               # [{doc_id, title, page, text_span}]
    confidence: float                   # 0.0 - 1.0 overall answer confidence
    graph_path: list[dict]              # [{node_id, node_type, label, edge_type}]
    query_type: str                     # "single-fact" | "multi-hop" | "aggregation" | "small_talk"
    agent_used: list[str]               # Which specialist agents contributed
    retrieval_strategy: str             # "vector" | "graph+vector" | "graph" | "none"
    latency_ms: int                     # End-to-end response time
    # Structured response fields
    supporting_detail: str = ""         # Optional additional context
    citation_note: str = ""             # Short footnote-style citation reference
    confidence_label: str = "Low"       # "High" | "Medium" | "Low"
    retrieval_path: str = "vector"      # "vector" | "graph" | "hybrid"
    # Guardrails fields (Section 1 + 3)
    groundedness_warning: list = field(default_factory=list)  # Unsupported claims list
    escalation_notice: str = ""         # Non-empty = safety-critical + low confidence

# ─────────────────────────────────────────────────────────────────────────────
# Document Types (for routing ingestion to the right parser)
# ─────────────────────────────────────────────────────────────────────────────

DOC_TYPES = Literal[
    "pid",              # P&ID / Engineering drawing
    "work_order",       # Maintenance work orders
    "sop",              # Standard Operating Procedures
    "inspection",       # Inspection reports
    "incident",         # Incident / near-miss reports
    "email",            # Email archives
    "spreadsheet",      # Excel / CSV data
    "manual",           # OEM / vendor manuals
    "regulation",       # Regulatory documents
    "generic",          # Fallback
]

# ─────────────────────────────────────────────────────────────────────────────
# Extraction Confidence Thresholds
# ─────────────────────────────────────────────────────────────────────────────

CONFIDENCE_THRESHOLDS = {
    "write_to_graph": 0.70,       # Minimum confidence to persist a fact
    "answer_to_user": 0.60,       # Minimum to include in answer (lower = hedged)
    "high_confidence": 0.90,      # Displayed as "verified" to user
    "retrieval_fallback": 0.70,   # If top result < this, use both retrieval paths
}
