"""
Fix 3 — the knowledge-graph extractor only ever sees scanned, clean text.

Audit finding: pipeline.py fed parsed["text"] (the raw document, including
chunks the injection scanner had just blocked) to the two-pass LLM extractor,
so blocked content could still be written into Neo4j.
"""
from backend.ingestion.pipeline import ingest_document
from tests.helpers import ATTACK, CLEAN, INDUSTRIAL_FP, install_ingest_fakes


async def test_blocked_chunk_never_reaches_graph_extractor(monkeypatch, tmp_path):
    f = tmp_path / "doc.txt"; f.write_text("x")
    seen = install_ingest_fakes(monkeypatch, [CLEAN, ATTACK])
    await ingest_document(str(f), "generic", {})
    assert seen["extract_text"] is not None
    assert "Pump P-101" in seen["extract_text"]
    assert "system prompt" not in seen["extract_text"].lower()


async def test_flagged_but_cleared_chunk_never_reaches_graph_extractor(monkeypatch, tmp_path):
    # Regex-flagged chunks are kept out of the graph even if the LLM cleared them:
    # a wrong fact in the graph is permanent, so the graph takes only fully clean text.
    f = tmp_path / "doc.txt"; f.write_text("y")
    seen = install_ingest_fakes(monkeypatch, [CLEAN, INDUSTRIAL_FP])
    await ingest_document(str(f), "generic", {})
    assert "Disregard the previous" not in seen["extract_text"]


async def test_document_with_no_clean_chunks_is_not_sent_to_graph(monkeypatch, tmp_path):
    f = tmp_path / "doc.txt"; f.write_text("z")
    seen = install_ingest_fakes(monkeypatch, [ATTACK])
    await ingest_document(str(f), "generic", {})
    assert seen["extract_calls"] == 0
