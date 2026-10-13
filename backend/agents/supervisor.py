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
import os
import re
import time
import uuid
from typing import Annotated, TypedDict

import aiosqlite
from langgraph.checkpoint.aiosqlite import AsyncSqliteSaver
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
from backend.guardrails.audit_log import log_high_stakes_query, log_review_event
from backend.review import queue as review_queue

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

# Returned when retrieval finds no trusted context. No agent is called, so the
# model cannot fall back to answering from its own memory.
ABSTAIN_ANSWER = (
    "I don't have enough trusted information in the knowledge base to answer this. "
    "No document passed the safety checks for this question."
)

# Human-in-the-loop (fix 6): shown to the user while a high-stakes answer is held.
PENDING_ANSWER = (
    "This question involves a safety-critical procedure. A qualified safety reviewer "
    "must approve the answer before it is shown. Your request is pending review."
)
REJECTED_ANSWER = (
    "A safety reviewer did not approve an answer to this question. "
    "Please consult your safety officer or the controlling SOP directly."
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
    # Human review state (fix 6)
    review_status: str          # "none" | "approved" | "edited" | "rejected"
    review_decision: dict       # written by the reviewer endpoint before resuming


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


async def abstain_node(state: SupervisorState) -> SupervisorState:
    """No trusted context was retrieved: answer with an explicit abstention."""
    return {
        **state,
        "final_answer": ABSTAIN_ANSWER,
        "supporting_detail": "",
        "citation_note": "",
        "citations": [],
        "confidence": 0.0,
        "confidence_label": "Low",
        "retrieval_path": "none",
        "graph_path": [],
        "agents_used": [],
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

    # Every agent computes confidence with the same function over the same
    # context, so confidence cannot choose between them. The primary answer is
    # the first keyword-matched specialist (most specific frame); the copilot
    # is the fallback when no specialist ran or all specialists failed.
    primary = _pick_primary(outputs)

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





def needs_human_review(state: SupervisorState) -> bool:
    """High-stakes answers are held for a reviewer (HITL_MODE=all), or only
    those not labelled High (HITL_MODE=low_confidence)."""
    if not state.get("is_high_stakes"):
        return False
    if settings.HITL_MODE == "low_confidence":
        return state.get("confidence_label") != "High"
    return True


async def release_node(state: SupervisorState) -> SupervisorState:
    """Runs only after a reviewer decision has been written to the paused
    thread (the graph is compiled with interrupt_before=["release"])."""
    decision = state.get("review_decision") or {}
    kind = decision.get("decision")
    update = {"escalation_notice": ""}
    if kind == "approve":
        update["review_status"] = "approved"
    elif kind == "edit":
        update.update(review_status="edited", final_answer=decision.get("edited_answer", ""),
                      supporting_detail="", citation_note="")
    else:  # reject, or anything unexpected: fail closed
        update.update(review_status="rejected", final_answer=REJECTED_ANSWER, supporting_detail="",
                      citation_note="", citations=[], graph_path=[])
    return {**state, **update}


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


def _pick_primary(outputs: list[dict]) -> dict:
    specialists = [o for o in outputs if o.get("agent_name") != "copilot"]
    return specialists[0] if specialists else outputs[0]


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

def build_supervisor(checkpointer=None):
    graph = StateGraph(SupervisorState)
    graph.add_node("classify", classify_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("dispatch", dispatch_specialists_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("guardrails", groundedness_check_node)  # Section 1 + 3
    graph.add_node("abstain", abstain_node)
    graph.add_node("release", release_node)  # human-review gate (fix 6)

    graph.set_entry_point("classify")

    def route_after_classify(state: SupervisorState):
        if state["query_type"] == "off-topic":
            return END
        return "retrieve"

    def route_after_retrieve(state: SupervisorState):
        # Abstain when nothing trusted was retrieved, instead of letting agents
        # answer from model memory.
        return "dispatch" if state["reranked_context"] else "abstain"

    graph.add_conditional_edges("classify", route_after_classify)
    graph.add_conditional_edges("retrieve", route_after_retrieve)
    graph.add_edge("abstain", END)
    graph.add_edge("dispatch", "synthesize")
    graph.add_edge("synthesize", "guardrails")  # guardrails wraps synthesis

    def route_after_guardrails(state: SupervisorState):
        # Deterministic rule — no LLM decides whether a human must review.
        return "release" if needs_human_review(state) else END

    graph.add_conditional_edges("guardrails", route_after_guardrails)
    graph.add_edge("release", END)

    # The graph pauses BEFORE "release"; the paused state is persisted by the
    # checkpointer so a reviewer can resume it later, even after a restart.
    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer, interrupt_before=["release"])
    return graph.compile()


# Compiled supervisor with a persistent SQLite checkpointer. aiosqlite
# connections are bound to an event loop, so one graph is kept per loop.
_supervisor_cache: dict = {"loop": None, "graph": None}


async def get_supervisor():
    loop = asyncio.get_running_loop()
    if _supervisor_cache["graph"] is None or _supervisor_cache["loop"] is not loop:
        os.makedirs(os.path.dirname(settings.CHECKPOINT_DB_PATH) or ".", exist_ok=True)
        conn = aiosqlite.connect(settings.CHECKPOINT_DB_PATH)
        conn.daemon = True  # aiosqlite runs a worker thread; never block interpreter exit
        await conn
        _supervisor_cache.update(loop=loop, graph=build_supervisor(AsyncSqliteSaver(conn)), conn=conn)
    return _supervisor_cache["graph"]


def reset_supervisor() -> None:
    """Drop the compiled graph (tests use this to simulate a process restart)."""
    _supervisor_cache.update(loop=None, graph=None, conn=None)


async def close_supervisor() -> None:
    """Close the checkpointer connection (called on app shutdown)."""
    conn = _supervisor_cache.get("conn")
    if conn is not None and _supervisor_cache.get("loop") is asyncio.get_running_loop():
        await conn.close()
    reset_supervisor()


def _thread(review_id: str) -> dict:
    return {"configurable": {"thread_id": review_id}}


def _response_from_state(state: dict, latency_ms: int, status: str, review_id: str = "") -> AgentResponse:
    return AgentResponse(
        answer=state["final_answer"],
        citations=state.get("citations", []),
        confidence=state.get("confidence", 0.0),
        graph_path=state.get("graph_path", []),
        query_type=state.get("query_type", ""),
        agent_used=state.get("agents_used", []),
        retrieval_strategy=state.get("retrieval_strategy", ""),
        latency_ms=latency_ms,
        supporting_detail=state.get("supporting_detail", ""),
        citation_note=state.get("citation_note", ""),
        confidence_label=state.get("confidence_label", "Low"),
        retrieval_path=state.get("retrieval_path", "vector"),
        groundedness_warning=state.get("groundedness_warning", []),
        escalation_notice=state.get("escalation_notice", ""),
        status=status,
        review_id=review_id,
    )


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
        review_status="none",
        review_decision={},
    )

    review_id = str(uuid.uuid4())  # also the LangGraph thread_id
    graph = await get_supervisor()
    final_state = await graph.ainvoke(initial_state, _thread(review_id))
    latency_ms = int((time.time() - start) * 1000)

    snapshot = await graph.aget_state(_thread(review_id))
    if snapshot.next and "release" in snapshot.next:
        # Interrupted before release: WITHHOLD the draft. Only the pending
        # notice and the review id leave the server.
        review_queue.add_pending(review_id, question)
        log_review_event("review_pending", review_id, question=question,
                         confidence=final_state.get("confidence"),
                         confidence_label=final_state.get("confidence_label"))
        return AgentResponse(
            answer=PENDING_ANSWER, citations=[], confidence=0.0, graph_path=[],
            query_type=final_state.get("query_type", ""), agent_used=final_state.get("agents_used", []),
            retrieval_strategy=final_state.get("retrieval_strategy", ""), latency_ms=latency_ms,
            confidence_label="Low", escalation_notice=PENDING_ANSWER,
            status="pending_review", review_id=review_id,
        )

    status = "abstained" if final_state["final_answer"] == ABSTAIN_ANSWER else "answered"
    return _response_from_state(final_state, latency_ms, status)


# ─────────────────────────────────────────────────────────────────────────────
# Human review API (fix 6)
# ─────────────────────────────────────────────────────────────────────────────

class ReviewNotFound(Exception):
    pass


class ReviewAlreadyDecided(Exception):
    pass


async def get_review_state(review_id: str) -> tuple[dict, dict]:
    """Return (queue row, graph state values) for a review id."""
    row = review_queue.get(review_id)
    if not row:
        raise ReviewNotFound(review_id)
    graph = await get_supervisor()
    snapshot = await graph.aget_state(_thread(review_id))
    return row, dict(snapshot.values or {})


async def submit_review(review_id: str, decision: str, reviewer: str,
                        edited_answer: str = "", note: str = "") -> AgentResponse:
    """Record a reviewer decision on a paused thread and resume the graph."""
    if not review_queue.get(review_id):
        raise ReviewNotFound(review_id)
    if not review_queue.claim(review_id, reviewer):
        raise ReviewAlreadyDecided(review_id)

    start = time.time()
    try:
        graph = await get_supervisor()
        await graph.aupdate_state(
            _thread(review_id),
            {"review_decision": {"decision": decision, "reviewer": reviewer,
                                 "edited_answer": edited_answer, "note": note}},
            as_node="guardrails",  # re-evaluates the guardrails edge -> next is still "release"
        )
        final_state = await graph.ainvoke(None, _thread(review_id))
    except Exception:
        review_queue.release_claim(review_id)
        raise

    status = final_state.get("review_status", "rejected")
    review_queue.finish(review_id, status)
    log_review_event("review_decision", review_id, reviewer=reviewer, decision=decision,
                     outcome=status, note=note)
    return _response_from_state(final_state, int((time.time() - start) * 1000), status, review_id)

