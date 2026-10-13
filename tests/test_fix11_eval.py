"""
Fix 11 — the evaluation set is grounded in the corpus and scores the real
retrieved contexts.

Audit findings: 3 of 5 ground truths referenced equipment that appears in no
document (K-101, P-203, V-301/OISD-118), and Ragas was given 200-char
PII-redacted citation snippets instead of the contexts the model saw.
"""
import sqlite3
from pathlib import Path

import backend.agents.supervisor as sup
from backend.eval.benchmark import BENCHMARK

STORE = Path(__file__).resolve().parents[1] / "data" / "chroma" / "chroma.sqlite3"


def _chunks_by_file():
    con = sqlite3.connect(f"file:{STORE}?mode=ro", uri=True)
    rows = con.execute("""
        select f.string_value, d.string_value from embedding_metadata f
        join embedding_metadata d on f.id = d.id
        where f.key = 'file_name' and d.key = 'chroma:document'""").fetchall()
    out = {}
    for name, text in rows:
        out.setdefault(name, []).append(text)
    return out


def test_every_ground_truth_exists_in_its_source_document():
    corpus = _chunks_by_file()
    missing = [b["question"] for b in BENCHMARK
               if not any(b["must_contain"] in c for c in corpus.get(b["expected_source"], []))]
    assert missing == [], f"ground truth not in corpus for: {missing}"


def test_eval_pipeline_uses_the_grounded_benchmark():
    src = (Path(__file__).resolve().parents[1] / "backend" / "eval" / "eval_pipeline.py").read_text()
    assert "from backend.eval.benchmark import BENCHMARK" in src
    assert '"ground_truth": "' not in src          # no inline (ungrounded) ground truths left
    assert "retrieved_contexts" in src and 'c.get("text_span"' not in src


async def test_response_exposes_full_retrieved_contexts(monkeypatch):
    full = "Pump P-101 vibration 4.1 mm/s RMS on 2024-03-15; parallel misalignment. " * 6

    async def _classify(q):
        return {"query_type": "single-fact", "reasoning": "t"}

    async def _vs(*a, **k):
        return [{"chunk_id": "c", "text": full, "score": 0.8,
                 "metadata": {"doc_id": "d", "file_name": "log.txt", "injection_flagged": False}}]

    async def _none(*a, **k):
        return []

    async def _grounded(**kw):
        return {"claims": [], "overall_grounded": True, "unsupported_claims": [], "skipped": False}

    async def _llm(self, s, u):
        return '{"answer": "ok", "supporting_detail": "", "citation_note": ""}'

    monkeypatch.setattr(sup, "classify_query", _classify)
    monkeypatch.setattr(sup, "vector_search", _vs)
    monkeypatch.setattr(sup, "graph_search", _none)
    monkeypatch.setattr(sup, "verify_groundedness", _grounded)
    monkeypatch.setattr(sup.CopilotAgent, "_call_llm", _llm)
    resp = await sup.run_query("What did vibration analysis find on P-101?")
    assert resp.retrieved_contexts == [full]          # full chunk, not a 200-char snippet
