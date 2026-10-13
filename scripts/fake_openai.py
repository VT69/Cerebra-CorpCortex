"""
Local stand-in for the OpenAI API, for smoke-testing the real server without
an API key. NOT a model: it returns schema-correct canned replies.

  embeddings -> the stored embedding of the lexically closest chunk in the
                committed Chroma store (so vector retrieval is exercised for real)
  chat       -> JSON/text shaped for whichever prompt is calling it

Run: uvicorn scripts.fake_openai:app --port 8811
Then start the API with OPENAI_BASE_URL=http://127.0.0.1:8811/v1
"""
import json
import re
import time

import chromadb
from fastapi import FastAPI, Request

from backend.config import settings

app = FastAPI()
_col = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR).get_collection(settings.CHROMA_COLLECTION_NAME)
_rows = _col.get(include=["documents", "embeddings"])
_tokens = [set(re.findall(r"[a-z0-9-]{3,}", d.lower())) for d in _rows["documents"]]


def _closest_embedding(text: str) -> list[float]:
    q = set(re.findall(r"[a-z0-9-]{3,}", text.lower()))
    best = max(range(len(_tokens)), key=lambda i: len(q & _tokens[i]))
    return list(_rows["embeddings"][best])


@app.post("/v1/embeddings")
async def embeddings(req: Request):
    body = await req.json()
    inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
    data = [{"object": "embedding", "index": i, "embedding": _closest_embedding(t)} for i, t in enumerate(inputs)]
    return {"object": "list", "data": data, "model": body.get("model"), "usage": {"prompt_tokens": 1, "total_tokens": 1}}


def _reply(messages: list[dict]) -> str:
    system = next((m["content"] for m in messages if m["role"] == "system"), "") or ""
    user = next((m["content"] for m in messages if m["role"] == "user"), "")
    user = user if isinstance(user, str) else json.dumps(user)
    if "query classifier" in system:
        return json.dumps({"query_type": "single-fact", "reasoning": "stub"})
    if "strict fact-checker" in system:
        return json.dumps({"claims": [{"claim": "stub", "status": "supported"}],
                           "overall_grounded": True, "unsupported_claims": []})
    if "security classifier" in system:
        t = user.lower()
        return json.dumps({"is_injection_attempt": "instructions" in t or "system prompt" in t, "reasoning": "stub"})
    if "Cypher" in system:
        return "MATCH (e:Equipment) RETURN e LIMIT 5"
    if "extraction engine" in system or "ontology verifier" in system:
        return json.dumps({"nodes": [], "edges": [], "verified_nodes": [], "verified_edges": []})
    ctx = re.search(r"\[Source 1[^\]]*\]\n(.{0,160})", user, re.S)
    snippet = ctx.group(1).strip().replace("\n", " ") if ctx else "no context"
    if "valid JSON object" in system:  # copilot
        return json.dumps({"answer": f"Per the retrieved document: {snippet}", "supporting_detail": "",
                           "citation_note": "stub"})
    return f"Per the retrieved document: {snippet}"


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    content = _reply(body["messages"])
    return {"id": "stub", "object": "chat.completion", "created": int(time.time()), "model": body.get("model"),
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 1}}
