"""
Fix 13 — /query is rate limited per client, bounding review-queue flooding.

Found while re-running the red-team table after fix 6: /query is
unauthenticated and every high-stakes question is now held for a human, so
one client could fill the reviewer queue without limit.
"""
import pytest
from fastapi.testclient import TestClient

import backend.api.main as main
from backend.config import settings
from backend.shared.ontology import AgentResponse


@pytest.fixture
def client(monkeypatch):
    async def _fake_run_query(question, **kw):
        return AgentResponse(answer="held", citations=[], confidence=0.0, graph_path=[], query_type="single-fact",
                             agent_used=[], retrieval_strategy="vector", latency_ms=1,
                             status="pending_review", review_id="r")
    monkeypatch.setattr(main, "run_query", _fake_run_query)
    monkeypatch.setattr(settings, "RATE_LIMIT_QUERIES_PER_MIN", 5, raising=False)
    limiter = getattr(main, "query_limiter", None)
    if limiter:
        limiter.reset()
    with TestClient(main.app) as c:
        yield c


def test_query_flood_is_rate_limited(client):
    codes = [client.post("/query", json={"question": "LOTO procedure for C-202?"}).status_code for _ in range(6)]
    assert codes[:5] == [200] * 5
    assert codes[5] == 429
