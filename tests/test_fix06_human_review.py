"""
Fix 6 — high-stakes answers are withheld until a human reviewer approves,
edits or rejects them (LangGraph interrupt + persistent SQLite checkpointer).

Audit finding: "escalation to a human" was only a banner shown next to the
answer. No human was notified, nothing was held, and LangGraph interrupt and
checkpointing were not used.
"""
import json
import os

import pytest
from fastapi.testclient import TestClient

import backend.agents.supervisor as sup
import backend.api.main as main


@__import__('pytest').fixture(autouse=True)
def _reset_query_limiter():
    main.query_limiter.reset()
from backend.agents.compliance import ComplianceAgent
from backend.agents.copilot import CopilotAgent
from backend.agents.lessons_learned import LessonsLearnedAgent
from backend.agents.maintenance import MaintenanceAgent
from backend.config import settings

DRAFT = "Isolate the C-202 drive at breaker MCC-4, apply lock and tag, then verify zero energy."
HIGH_STAKES_Q = "What is the LOTO procedure for conveyor C-202?"
NORMAL_Q = "What was the vibration reading of P-101 on 2024-03-15?"
REVIEWER = {"X-API-Key": os.environ["REVIEWER_API_KEY"]}


@pytest.fixture
def client(monkeypatch):
    async def _classify(q):
        return {"query_type": "single-fact", "reasoning": "t"}

    async def _vs(*a, **k):
        return [{"chunk_id": "c", "text": "LOTO SOP VSW-SAF-042 section 3.", "score": 0.9,
                 "metadata": {"doc_id": "d", "file_name": "Vindhya_Steel_LOTO_SOP.txt",
                              "injection_flagged": False}}]

    async def _no_graph(*a, **k):
        return []

    async def _grounded(**kw):
        return {"claims": [], "overall_grounded": True, "unsupported_claims": [], "skipped": False}

    async def _llm(self, system_prompt, user_prompt):
        return json.dumps({"answer": DRAFT, "supporting_detail": "", "citation_note": ""})

    monkeypatch.setattr(sup, "classify_query", _classify)
    monkeypatch.setattr(sup, "vector_search", _vs)
    monkeypatch.setattr(sup, "graph_search", _no_graph)
    monkeypatch.setattr(sup, "verify_groundedness", _grounded)
    for cls in (CopilotAgent, MaintenanceAgent, ComplianceAgent, LessonsLearnedAgent):
        monkeypatch.setattr(cls, "_call_llm", _llm)
    with TestClient(main.app) as c:
        yield c


def _ask(client, q):
    r = client.post("/query", json={"question": q})
    assert r.status_code == 200, r.text
    return r.json()


def test_high_stakes_answer_is_withheld(client):
    body = _ask(client, HIGH_STAKES_Q)
    assert body.get("status") == "pending_review"
    assert body.get("review_id")
    assert DRAFT not in json.dumps(body), "draft answer leaked before review"
    assert body["citations"] == []


def test_normal_question_is_answered_directly(client):
    body = _ask(client, NORMAL_Q)
    assert body.get("status") == "answered"
    assert body["answer"] == DRAFT


def test_reviewer_endpoints_require_reviewer_key(client):
    assert client.get("/review/pending").status_code == 401
    rid = _ask(client, HIGH_STAKES_Q)["review_id"]
    r = client.post(f"/review/{rid}", json={"decision": "approve", "reviewer": "x"},
                    headers={"X-API-Key": os.environ["INGEST_API_KEY"]})  # wrong role's key
    assert r.status_code == 401


def test_pending_list_shows_draft_to_reviewer(client):
    rid = _ask(client, HIGH_STAKES_Q)["review_id"]
    items = client.get("/review/pending", headers=REVIEWER).json()
    item = next(i for i in items if i["review_id"] == rid)
    assert item["draft_answer"] == DRAFT
    assert item["question"] == HIGH_STAKES_Q
    assert client.get(f"/answer/{rid}").json()["status"] == "pending_review"


def test_approve_releases_answer_and_logs_decision(client):
    rid = _ask(client, HIGH_STAKES_Q)["review_id"]
    r = client.post(f"/review/{rid}", json={"decision": "approve", "reviewer": "safety.officer.1"},
                    headers=REVIEWER)
    assert r.status_code == 200, r.text
    released = client.get(f"/answer/{rid}").json()
    assert released["status"] == "approved"
    assert released["answer"] == DRAFT

    with open(os.path.join(settings.AUDIT_DIR, "review_audit.jsonl")) as f:
        events = [json.loads(line) for line in f if rid in line]
    decision = [e for e in events if e["event"] == "review_decision"][-1]
    assert decision["reviewer"] == "safety.officer.1"
    assert decision["decision"] == "approve"
    assert decision["_logged_at"]


def test_edit_releases_reviewer_text(client):
    rid = _ask(client, HIGH_STAKES_Q)["review_id"]
    edited = "Follow SOP VSW-SAF-042 sections 3.1-3.6; release belt tension before isolation."
    client.post(f"/review/{rid}", json={"decision": "edit", "reviewer": "so2", "edited_answer": edited},
                headers=REVIEWER)
    released = client.get(f"/answer/{rid}").json()
    assert released["status"] == "edited" and released["answer"] == edited


def test_reject_never_releases_draft(client):
    rid = _ask(client, HIGH_STAKES_Q)["review_id"]
    client.post(f"/review/{rid}", json={"decision": "reject", "reviewer": "so3", "note": "wrong breaker"},
                headers=REVIEWER)
    released = client.get(f"/answer/{rid}").json()
    assert released["status"] == "rejected"
    assert DRAFT not in json.dumps(released)


def test_decision_is_final(client):
    rid = _ask(client, HIGH_STAKES_Q)["review_id"]
    ok = client.post(f"/review/{rid}", json={"decision": "approve", "reviewer": "a"}, headers=REVIEWER)
    again = client.post(f"/review/{rid}", json={"decision": "reject", "reviewer": "b"}, headers=REVIEWER)
    assert ok.status_code == 200 and again.status_code == 409


def test_pending_review_survives_restart(client, monkeypatch):
    rid = _ask(client, HIGH_STAKES_Q)["review_id"]
    # Simulate a process restart: drop the compiled graph and its DB connection.
    sup.reset_supervisor()
    r = client.post(f"/review/{rid}", json={"decision": "approve", "reviewer": "after-restart"},
                    headers=REVIEWER)
    assert r.status_code == 200, r.text
    assert client.get(f"/answer/{rid}").json()["answer"] == DRAFT
