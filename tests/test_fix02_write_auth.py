"""
Fix 2 — write endpoints require an API key and are rate limited.

Audit finding: /ingest and /webhook/qms/incident let anyone write to the
knowledge base, /eval/run let anyone spend OpenAI budget, and the upload
filename was joined into a path unsanitised.
"""
import os

import pytest
from fastapi.testclient import TestClient

import backend.api.main as main
import backend.graph.writer as writer
from backend.config import settings

KEY = os.environ["INGEST_API_KEY"]
WEBHOOK = {"incident_id": "INC-1", "equipment_id": "P-101",
           "description": "x", "severity": "High", "date": "2024-01-01"}


@pytest.fixture
def client(monkeypatch):
    calls = {"ingest": [], "graph_runs": 0}

    async def _fake_ingest(path, doc_type, cache):
        calls["ingest"].append(path)
        return {"status": "success", "doc_id": "d", "chunks": 1, "nodes": 0, "edges": 0}

    class _Res:
        async def single(self):
            return None

    class _Sess:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def run(self, *a, **k):
            calls["graph_runs"] += 1
            return _Res()

    class _Drv:
        def session(self, **k): return _Sess()
        async def close(self): pass

    async def _get_driver(*a, **k):
        return _Drv()

    monkeypatch.setattr(main, "ingest_document", _fake_ingest)
    monkeypatch.setattr(writer, "get_driver", _get_driver)
    limiter = getattr(main, "write_limiter", None)
    if limiter:
        limiter.reset()
    with TestClient(main.app) as c:  # context manager runs lifespan (creates data dirs)
        c.calls = calls
        yield c


def _upload(name="note.txt"):
    return {"file": (name, b"hello world", "text/plain")}


def test_ingest_rejects_missing_key(client):
    r = client.post("/ingest", files=_upload())
    assert r.status_code == 401
    assert client.calls["ingest"] == []


def test_ingest_rejects_wrong_key(client):
    r = client.post("/ingest", files=_upload(), headers={"X-API-Key": "wrong"})
    assert r.status_code == 401
    assert client.calls["ingest"] == []


@pytest.mark.parametrize("headers", [{"X-API-Key": KEY}, {"Authorization": f"Bearer {KEY}"}])
def test_ingest_accepts_valid_key(client, headers):
    r = client.post("/ingest", files=_upload(), headers=headers)
    assert r.status_code == 200, r.text
    assert len(client.calls["ingest"]) == 1


def test_webhook_rejects_missing_key_and_never_touches_graph(client):
    r = client.post("/webhook/qms/incident", json=WEBHOOK)
    assert r.status_code == 401
    assert client.calls["graph_runs"] == 0


def test_eval_run_requires_key(client):
    r = client.post("/eval/run")
    assert r.status_code == 401


def test_writes_are_rate_limited(client):
    limit = settings.RATE_LIMIT_WRITES_PER_MIN
    codes = [client.post("/ingest", files=_upload(), headers={"X-API-Key": KEY}).status_code
             for _ in range(limit + 1)]
    assert codes[:limit] == [200] * limit
    assert codes[-1] == 429


def test_writes_fail_closed_when_no_key_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "INGEST_API_KEY", None)
    r = client.post("/ingest", files=_upload(), headers={"X-API-Key": KEY})
    assert r.status_code == 503
    assert client.calls["ingest"] == []


def test_upload_filename_cannot_escape_upload_dir(client):
    r = client.post("/ingest", files=_upload("../../escape.txt"), headers={"X-API-Key": KEY})
    assert r.status_code == 200, r.text
    saved = os.path.realpath(client.calls["ingest"][0])
    assert os.path.dirname(saved) == os.path.realpath(settings.DOC_UPLOAD_DIR)
