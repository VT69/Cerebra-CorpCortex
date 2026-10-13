"""
Fix 5 — confidence uses the full 0-1 range, is computed the same way for every
agent, and "High" is reachable.

Audit finding (verified by running the old code): the reranker multiplied
cosine by 0.6 and the copilot's thresholds assumed raw cosine, so copilot
confidence maxed out at 0.696 and the High label (>= 0.85) was unreachable.
Specialists returned hard-coded 0.80 / 0.78 / 0.75 regardless of retrieval,
so they always beat the copilot.
"""
import pytest

import backend.agents.supervisor as sup
from backend.agents.compliance import ComplianceAgent
from backend.agents.copilot import CopilotAgent
from backend.agents.lessons_learned import LessonsLearnedAgent
from backend.agents.maintenance import MaintenanceAgent
from backend.retrieval.reranker import rerank

AGENTS = [CopilotAgent, MaintenanceAgent, ComplianceAgent, LessonsLearnedAgent]


def _ctx(cosine):
    return rerank([{"text": "Pump P-101 alignment completed 2024-04-02.", "score": cosine,
                    "metadata": {"doc_id": "d", "file_name": "log.txt"}}], [])


async def _llm(self, system_prompt, user_prompt):
    return '{"answer": "Laser alignment was completed.", "supporting_detail": "", "citation_note": ""}'


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    for cls in AGENTS:
        monkeypatch.setattr(cls, "_call_llm", _llm)


def test_reranker_keeps_raw_cosine_as_relevance_score():
    assert _ctx(0.95)[0]["final_score"] == pytest.approx(0.95)


async def test_strong_retrieval_reaches_high_band():
    out = await CopilotAgent().run("q", _ctx(1.0), [])
    assert out["confidence"] > 0.696          # the old ceiling
    out = await CopilotAgent().run("q", _ctx(0.95), [])
    assert out["confidence"] >= 0.85          # High label threshold


@pytest.mark.parametrize("cosine", [0.95, 0.6, 0.3])
async def test_all_agents_compute_the_same_confidence(cosine):
    ctx = _ctx(cosine)
    scores = {cls.__name__: (await cls().run("q", ctx, []))["confidence"] for cls in AGENTS}
    assert len(set(scores.values())) == 1, scores


async def test_specialist_confidence_drops_with_weak_retrieval():
    out = await MaintenanceAgent().run("q", _ctx(0.30), [])
    assert out["confidence"] < 0.60          # old code: always 0.80


async def test_end_to_end_label_can_be_high(monkeypatch):
    async def _classify(q):
        return {"query_type": "single-fact", "reasoning": "t"}

    async def _vs(*a, **k):
        return [{"chunk_id": "c", "text": "Pump P-101 alignment completed 2024-04-02.", "score": 0.95,
                 "metadata": {"doc_id": "d", "file_name": "log.txt", "injection_flagged": False}}]

    async def _no_graph(*a, **k):
        return []

    async def _grounded(**kw):
        return {"claims": [{"claim": "x", "status": "supported"}], "overall_grounded": True,
                "unsupported_claims": [], "skipped": False}

    monkeypatch.setattr(sup, "classify_query", _classify)
    monkeypatch.setattr(sup, "vector_search", _vs)
    monkeypatch.setattr(sup, "graph_search", _no_graph)
    monkeypatch.setattr(sup, "verify_groundedness", _grounded)
    resp = await sup.run_query("When was the P-101 maintenance alignment done?")
    assert resp.confidence_label == "High"
    assert "maintenance" in resp.agent_used
