"""
LangGraph Supervisor Agent — orchestrates specialist agents.
Mohit owns this file.

Flow:
  1. Small-talk check (short-circuit — no retrieval)
  2. Classify query type
  3. Run hybrid retrieval (vector + graph as needed)
  4. Dispatch to relevant specialist agent(s) in parallel
  5. Compose final answer from specialist outputs
  6. Return AgentResponse with citations, confidence, graph_path

Agents share an immutable context list (NOT mutable shared state) to prevent
ordering bugs — each agent appends its output, others read it read-only.
"""
import asyncio
import json
import re
import time
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from backend.shared.ontology import AgentResponse
from backend.retrieval.classifier import classify_query
from backend.retrieval.vector_search import vector_search, needs_graph_fallback
from backend.retrieval.graph_search import graph_search
from backend.retrieval.reranker import rerank
from backend.agents.copilot import CopilotAgent
from backend.agents.maintenance import MaintenanceAgent
from backend.agents.compliance import ComplianceAgent
from backend.agents.lessons_learned import LessonsLearnedAgent
from backend.config import settings
from openai import AsyncOpenAI

# Guardrails imports
from backend.guardrails.groundedness import verify_groundedness, apply_groundedness_to_confidence
from backend.guardrails.severity import is_high_stakes, get_escalation_notice
from backend.guardrails.audit_log import log_high_stakes_query

_oai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# ─────────────────────────────────────────────────────────────────────────────
# Small-talk detection (Section 2)
# ─────────────────────────────────────────────────────────────────────────────

SMALL_TALK = {
    "hi", "hello", "hey", "hii", "hiii", "thanks", "thank you", "thank u",
    "bye", "goodbye", "ok", "okay", "cool", "great", "nice", "awesome",
    "sure", "yep", "yes", "no", "nope", "good", "perfect", "got it",
    "alright", "right", "sounds good", "makes sense"
}


def is_small_talk(query: str) -> bool:
    """Cheap deterministic check — no LLM call needed."""
    normalized = query.strip().lower().rstrip("!.?,")
    if normalized in SMALL_TALK:
        return True
    # Also catch very short 2-word phrases that are common filler
    words = normalized.split()
    if len(words) <= 2 and all(w in SMALL_TALK or len(w) <= 3 for w in words):
        return True
    return False


SMALL_TALK_REPLY = (
    "Hi! I'm IndustrialIQ — your AI assistant for plant knowledge. "
    "Ask me anything about your equipment, maintenance records, inspection reports, "
    "or safety regulations (OSHA, OISD, etc.)."
)

# ─────────────────────────────────────────────────────────────────────────────
# Citation deduplication (Section 3)
# ─────────────────────────────────────────────────────────────────────────────

def dedupe_citations(citations: list[dict]) -> list[dict]:
    """
    Collapse multiple chunks from the same source document into one card.
    
    Uses TITLE as the primary merge key (not doc_id), because:
    - doc_id may differ per-chunk if the per-document UUID wasn't propagated
    - title (filename) is always the same for all chunks of a document
    
    - One card per unique document title
    - Excerpts merged (unique only), capped at 2 shown + extra count
    - Score = max across all chunks
    """
    merged: dict[str, dict] = {}
    for c in citations:
        # Use title as primary key — always unique per document
        # Fall back to doc_id only if title is missing
        title = c.get("title", "").strip()
        merge_key = title or c.get("doc_id", "unknown")

        if merge_key not in merged:
            merged[merge_key] = {
                "doc_id": c.get("doc_id", ""),
                "title": title or "Unknown Document",
                "doc_type": c.get("doc_type", ""),
                "score": c.get("score", 0),
                "text_span": c.get("text_span", ""),
                "source": c.get("source", "vector"),
                "chunk_index": c.get("chunk_index", 0),
                "_all_excerpts": [c.get("text_span", "")],
            }
        else:
            # Keep highest score
            merged[merge_key]["score"] = max(merged[merge_key]["score"], c.get("score", 0))
            # Add unique excerpts only
            excerpt = c.get("text_span", "")
            if excerpt and excerpt not in merged[merge_key]["_all_excerpts"]:
                merged[merge_key]["_all_excerpts"].append(excerpt)

    result = []
    for card in sorted(merged.values(), key=lambda x: -x["score"]):
        excerpts = card.pop("_all_excerpts", [])
        extra = len(excerpts) - 2
        card["text_span"] = excerpts[0] if excerpts else ""
        card["extra_excerpts"] = excerpts[1:2]  # 2nd excerpt if available
        card["extra_count"] = max(0, extra)
        result.append(card)

    print(f"[Citations] {len(citations)} raw → {len(result)} unique after dedup")
    return result




# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────

class SupervisorState(TypedDict):
    question: str
    query_type: str
    query_reasoning: str
    vector_hits: list
    graph_hits: list
    reranked_context: list
    retrieval_strategy: str
    # Immutable specialist outputs (append-only list)
    specialist_outputs: list[dict]
    # Final
    final_answer: str
    supporting_detail: str
    citation_note: str
    citations: list[dict]
    confidence: float
    confidence_label: str
    retrieval_path: str
    graph_path: list[dict]
    agents_used: list[str]
    start_time: float
    # Guardrails state (Sections 1, 3)
    is_high_stakes: bool
    groundedness_warning: list[str]
    escalation_notice: str


# ─────────────────────────────────────────────────────────────────────────────
# Node functions
# ─────────────────────────────────────────────────────────────────────────────

async def classify_node(state: SupervisorState) -> SupervisorState:
    result = await classify_query(state["question"])

    # Section 3: severity flag (keyword check, no LLM call)
    high_stakes = is_high_stakes(state["question"])

    if result["query_type"] == "off-topic":
        return {
            **state,
            "query_type": "off-topic",
            "query_reasoning": result["reasoning"],
            "final_answer": "This seems outside my scope as an industrial intelligence assistant. I'm best equipped to help you with safety procedures, maintenance records, compliance audits, and equipment history.",
            "confidence_label": "High",
            "confidence": 1.0,
            "retrieval_strategy": "none",
            "is_high_stakes": high_stakes,
            "groundedness_warning": [],
            "escalation_notice": "",
        }

    return {
        **state,
        "query_type": result["query_type"],
        "query_reasoning": result["reasoning"],
        "is_high_stakes": high_stakes,
        "groundedness_warning": [],
        "escalation_notice": "",
    }


async def retrieve_node(state: SupervisorState) -> SupervisorState:
    question = state["question"]
    query_type = state["query_type"]

    # Always run vector search
    v_hits = await vector_search(question, top_k=settings.VECTOR_TOP_K)

    # Run graph search if: multi-hop/aggregation OR vector confidence is low
    g_hits = []
    strategy = "vector"
    if query_type in ("multi-hop", "aggregation") or needs_graph_fallback(v_hits):
        g_hits = await graph_search(question, query_type)
        strategy = "graph+vector"

    reranked = rerank(v_hits, g_hits)

    return {
        **state,
        "vector_hits": v_hits,
        "graph_hits": g_hits,
        "reranked_context": reranked,
        "retrieval_strategy": strategy,
    }


async def dispatch_specialists_node(state: SupervisorState) -> SupervisorState:
    """
    Dispatch to specialist agents in parallel.
    Each agent receives the question + reranked context (read-only).
    Each agent appends its output to specialist_outputs.
    """
    context = state["reranked_context"]
    question = state["question"]
    existing_outputs = state.get("specialist_outputs", [])

    # Determine which specialists to invoke based on question keywords
    agents_to_run = _select_agents(question)

    # Run in parallel — agents read shared context but write to separate outputs
    tasks = []
    for agent_name in agents_to_run:
        agent = _get_agent(agent_name)
        if agent:
            tasks.append(_run_agent(agent_name, agent, question, context, existing_outputs))

    outputs = await asyncio.gather(*tasks, return_exceptions=True)

    new_outputs = list(existing_outputs)
    agents_used = []
    for i, output in enumerate(outputs):
        if isinstance(output, Exception):
            print(f"[Supervisor] Agent {agents_to_run[i]} failed: {output}")
        else:
            new_outputs.append(output)
            agents_used.append(agents_to_run[i])

    return {**state, "specialist_outputs": new_outputs, "agents_used": agents_used}


async def synthesize_node(state: SupervisorState) -> SupervisorState:
    """
    Compose the final answer from specialist outputs.

    NO extra LLM call here — copilot already produced structured JSON.
    Confidence is computed deterministically from vector scores (fast + calibrated).
    """
    outputs = state.get("specialist_outputs", [])
    retrieval_strategy = state.get("retrieval_strategy", "vector")

    # Map internal strategy label to retrieval_path value
    if "graph" in retrieval_strategy and "vector" in retrieval_strategy:
        retrieval_path = "hybrid"
    elif "graph" in retrieval_strategy:
        retrieval_path = "graph"
    else:
        retrieval_path = "vector"

    if not outputs:
        return {
            **state,
            "final_answer": "I couldn't find relevant information for your question in the knowledge base.",
            "supporting_detail": "Try rephrasing your question or check that relevant documents have been ingested.",
            "citation_note": "",
            "citations": [],
            "confidence": 0.0,
            "confidence_label": "Low",
            "retrieval_path": retrieval_path,
            "graph_path": [],
        }

    # Use the highest-confidence specialist output as primary
    # (copilot always runs; maintenance/compliance add on top)
    primary = max(outputs, key=lambda x: x.get("confidence", 0))

    # Pull structured fields from copilot's output
    final_answer = primary.get("answer", "")
    supporting_detail = primary.get("supporting_detail", "")
    citation_note = primary.get("citation_note", "")
    confidence = primary.get("confidence", 0.0)

    # Confidence label from the deterministic score (not LLM-generated)
    if confidence >= 0.85:
        confidence_label = "High"
    elif confidence >= 0.60:
        confidence_label = "Medium"
    else:
        confidence_label = "Low"

    # Merge citations from ALL specialist outputs, deduplicate by title (Section 3)
    all_citations = []
    seen_keys = set()
    for output in outputs:
        for citation in output.get("citations", []):
            # Key by title (filename) — most reliable unique identifier per document
            title_key = citation.get("title", "").strip().lower()
            doc_key = title_key or citation.get("doc_id", "")
            if doc_key not in seen_keys:
                seen_keys.add(doc_key)
                all_citations.append(citation)

    deduped_citations = dedupe_citations(all_citations)

    # Merge graph paths
    all_paths = []
    for output in outputs:
        all_paths.extend(output.get("graph_path", []))

    return {
        **state,
        "final_answer": final_answer,
        "supporting_detail": supporting_detail,
        "citation_note": citation_note,
        "citations": deduped_citations[:8],  # Max 8 unique source cards
        "confidence": round(confidence, 3),
        "confidence_label": confidence_label,
        "retrieval_path": retrieval_path,
        "graph_path": all_paths[:20],
    }


async def groundedness_check_node(state: SupervisorState) -> SupervisorState:
    """
    Section 1: Independent groundedness verification after synthesis.
    Section 3: Severity escalation check (uses finalized confidence_label).

    Short-circuits for small_talk and off-topic (no retrieval context).
    """
    query_type = state.get("query_type", "")
    final_answer = state.get("final_answer", "")
    reranked_context = state.get("reranked_context", [])
    confidence = state.get("confidence", 0.0)
    confidence_label = state.get("confidence_label", "Low")
    question = state["question"]

    # Extract raw text from context for groundedness check
    context_texts = [item.get("text", "") for item in reranked_context if item.get("text")]

    # Section 1: Groundedness verification
    groundedness = await verify_groundedness(
        answer=final_answer,
        context_chunks=context_texts,
        query_type=query_type,
    )

    # Adjust confidence based on groundedness result
    new_confidence, new_label, warning_list = apply_groundedness_to_confidence(
        groundedness=groundedness,
        current_confidence=confidence,
        current_label=confidence_label,
    )

    # Section 3: Severity escalation (uses finalized label after groundedness cap)
    high_stakes = state.get("is_high_stakes", False)
    escalation_notice = get_escalation_notice(
        query=question,
        confidence_label=new_label,
        high_stakes=high_stakes,
    )

    # Audit log — every high-stakes query regardless of whether escalation fired
    if high_stakes:
        log_high_stakes_query(
            query=question,
            confidence=new_confidence,
            confidence_label=new_label,
            escalated=bool(escalation_notice),
            escalation_notice=escalation_notice,
        )

    return {
        **state,
        "confidence": new_confidence,
        "confidence_label": new_label,
        "groundedness_warning": warning_list,
        "escalation_notice": escalation_notice,
    }





# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _select_agents(question: str) -> list[str]:
    """Simple keyword-based agent selector."""
    q = question.lower()
    agents = ["copilot"]  # Always include general copilot

    if any(k in q for k in ["maintenance", "repair", "failure", "rca", "root cause", "work order", "downtime", "mtbf"]):
        agents.append("maintenance")

    if any(k in q for k in ["compliance", "regulation", "oisd", "peso", "factory act", "audit", "gap", "non-conformance"]):
        agents.append("compliance")

    if any(k in q for k in ["lesson", "incident", "near miss", "failure pattern", "repeat", "recurring", "history"]):
        agents.append("lessons_learned")

    return agents


def _get_agent(name: str):
    agents = {
        "copilot": CopilotAgent(),
        "maintenance": MaintenanceAgent(),
        "compliance": ComplianceAgent(),
        "lessons_learned": LessonsLearnedAgent(),
    }
    return agents.get(name)


async def _run_agent(
    name: str,
    agent,
    question: str,
    context: list[dict],
    prior_outputs: list[dict],
) -> dict:
    """Run a single specialist agent and return its output dict."""
    result = await agent.run(question, context, prior_outputs)
    result["agent_name"] = name
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Build LangGraph
# ─────────────────────────────────────────────────────────────────────────────

def build_supervisor() -> StateGraph:
    graph = StateGraph(SupervisorState)
    graph.add_node("classify", classify_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("dispatch", dispatch_specialists_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("guardrails", groundedness_check_node)  # Section 1 + 3

    graph.set_entry_point("classify")

    def route_after_classify(state: SupervisorState):
        if state["query_type"] == "off-topic":
            return END
        return "retrieve"

    graph.add_conditional_edges("classify", route_after_classify)
    graph.add_edge("retrieve", "dispatch")
    graph.add_edge("dispatch", "synthesize")
    graph.add_edge("synthesize", "guardrails")  # guardrails wraps synthesis
    graph.add_edge("guardrails", END)

    return graph.compile()


# Compiled supervisor (singleton — import this)
supervisor = build_supervisor()


async def run_query(question: str) -> AgentResponse:
    """Main entry point — run the full supervisor pipeline.
    Small talk is short-circuited here — no retrieval, no citations.
    """
    start = time.time()

    # Section 2: short-circuit small talk
    if is_small_talk(question):
        latency_ms = int((time.time() - start) * 1000)
        return AgentResponse(
            answer=SMALL_TALK_REPLY,
            citations=[],
            confidence=1.0,
            graph_path=[],
            query_type="small_talk",
            agent_used=[],
            retrieval_strategy="none",
            latency_ms=latency_ms,
        )

    initial_state = SupervisorState(
        question=question,
        query_type="",
        query_reasoning="",
        vector_hits=[],
        graph_hits=[],
        reranked_context=[],
        retrieval_strategy="",
        specialist_outputs=[],
        final_answer="",
        supporting_detail="",
        citation_note="",
        citations=[],
        confidence=0.0,
        confidence_label="Low",
        retrieval_path="vector",
        graph_path=[],
        agents_used=[],
        start_time=start,
        # Guardrails initial values
        is_high_stakes=False,
        groundedness_warning=[],
        escalation_notice="",
    )

    final_state = await supervisor.ainvoke(initial_state)
    latency_ms = int((time.time() - start) * 1000)

    return AgentResponse(
        answer=final_state["final_answer"],
        citations=final_state["citations"],
        confidence=final_state["confidence"],
        graph_path=final_state["graph_path"],
        query_type=final_state["query_type"],
        agent_used=final_state.get("agents_used", []),
        retrieval_strategy=final_state["retrieval_strategy"],
        latency_ms=latency_ms,
        supporting_detail=final_state.get("supporting_detail", ""),
        citation_note=final_state.get("citation_note", ""),
        confidence_label=final_state.get("confidence_label", "Low"),
        retrieval_path=final_state.get("retrieval_path", "vector"),
        groundedness_warning=final_state.get("groundedness_warning", []),
        escalation_notice=final_state.get("escalation_notice", ""),
    )

