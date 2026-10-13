"""
Fix 4 — injection-flagged (or never-scanned) chunks are never returned, and
the system abstains instead of answering from untrusted or empty context.

Audit finding: vector_search.py returned flagged chunks whenever no clean
chunk matched ("never return empty"), so an attacker who made their poisoned
chunk the only match got it into the prompt. With empty context, agents
answered from model memory.
"""
import types

import backend.agents.supervisor as sup
import backend.retrieval.vector_search as vs

FLAGGED = {"doc_id": "d1", "file_name": "evil.txt", "injection_flagged": True}
UNSCANNED = {"doc_id": "d2", "file_name": "legacy.pdf"}  # pre-scanner chunk: no scan metadata
CLEAN = {"doc_id": "d3", "file_name": "ok.txt", "injection_flagged": False}


class _Coll:
    def __init__(self, metas):
        self.metas = metas

    def query(self, **kw):
        n = len(self.metas)
        return {"ids": [[f"c{i}" for i in range(n)]], "documents": [[f"text {i}" for i in range(n)]],
                "metadatas": [self.metas], "distances": [[0.2] * n]}


def _patch_store(monkeypatch, metas):
    async def _embed(**kw):
        return types.SimpleNamespace(data=[types.SimpleNamespace(embedding=[0.0] * 8)])
    monkeypatch.setattr(vs._oai.embeddings, "create", _embed)
    monkeypatch.setattr(vs, "_get_collection", lambda: _Coll(metas))


async def test_flagged_chunks_not_returned_even_when_nothing_else_matches(monkeypatch):
    _patch_store(monkeypatch, [FLAGGED])
    assert await vs.vector_search("q") == []


async def test_unscanned_legacy_chunks_are_treated_as_untrusted(monkeypatch):
    _patch_store(monkeypatch, [UNSCANNED])
    assert await vs.vector_search("q") == []


async def test_clean_chunks_still_returned(monkeypatch):
    _patch_store(monkeypatch, [FLAGGED, CLEAN, UNSCANNED])
    hits = await vs.vector_search("q")
    assert [h["metadata"]["doc_id"] for h in hits] == ["d3"]


async def test_supervisor_abstains_without_calling_any_agent(monkeypatch):
    called = []

    async def _classify(q):
        return {"query_type": "single-fact", "reasoning": "t"}

    async def _empty(*a, **k):
        return []

    async def _agent_run(self, *a, **k):
        called.append(type(self).__name__)
        return {"answer": "made up from model memory", "citations": [], "confidence": 0.8, "graph_path": []}

    monkeypatch.setattr(sup, "classify_query", _classify)
    monkeypatch.setattr(sup, "vector_search", _empty)
    monkeypatch.setattr(sup, "graph_search", _empty)
    for cls in (sup.CopilotAgent, sup.MaintenanceAgent, sup.ComplianceAgent, sup.LessonsLearnedAgent):
        monkeypatch.setattr(cls, "run", _agent_run)

    resp = await sup.run_query("What was the root cause of the C-202 failure?")
    assert called == []
    assert resp.answer == sup.ABSTAIN_ANSWER
    assert resp.confidence == 0.0
    assert resp.confidence_label == "Low"
    assert resp.citations == []
