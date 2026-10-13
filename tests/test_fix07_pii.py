"""
Fix 7 — PII regexes cover Indian IDs without leaking digits, and redaction is
applied to the answer text and the audit logs, not only citation snippets.

Audit findings (verified by running the old code):
  '+91 98765 43210'      -> '[REDACTED PHONE]0'   (one digit leaked)
  'Aadhaar 123456789012' -> unchanged              (unspaced Aadhaar missed)
  'pan abcde1234f'       -> unchanged              (lowercase PAN missed)
  'Part no. 12345-67890' -> '[REDACTED PHONE]'     (false positive)
  answer text and audit logs were never redacted
"""
import json
import os

import pytest
from fastapi.testclient import TestClient

import backend.api.main as main
from backend.config import settings
from backend.guardrails.audit_log import log_high_stakes_query, log_injection_attempt
from backend.guardrails.pii import redact_pii
from backend.shared.ontology import AgentResponse

PII_SENTENCE = "Call Rajesh at +91 98765 43210 or rajesh.sharma@vsw.in, Aadhaar 123456789012, PAN abcde1234f"
RAW_FRAGMENTS = ["98765", "43210", "rajesh.sharma@vsw.in", "123456789012", "abcde1234f"]


@pytest.mark.parametrize("text,expected", [
    ("Call Rajesh at +91 98765 43210 or rajesh.sharma@vsw.in",
     "Call Rajesh at [REDACTED PHONE] or [REDACTED EMAIL]"),
    ("Mobile 9876543210", "Mobile [REDACTED PHONE]"),
    ("Aadhaar 1234 5678 9012", "Aadhaar [REDACTED AADHAAR]"),
    ("Aadhaar 123456789012", "Aadhaar [REDACTED AADHAAR]"),
    ("Aadhaar 1234-5678-9012", "Aadhaar [REDACTED AADHAAR]"),
    ("PAN ABCDE1234F", "PAN [REDACTED PAN]"),
    ("pan abcde1234f", "pan [REDACTED PAN]"),
    ("Tel (022) 2345 6789", "Tel [REDACTED PHONE]"),
    ("Part no. 12345-67890", "Part no. 12345-67890"),          # not a mobile: must survive
    ("Vibration 4.1 mm/s on 2024-03-15", "Vibration 4.1 mm/s on 2024-03-15"),
])
def test_redaction_patterns(text, expected):
    assert redact_pii(text) == expected


def test_answer_text_is_redacted_in_api_response(monkeypatch):
    async def _fake_run_query(question, **kw):
        return AgentResponse(answer=PII_SENTENCE, citations=[], confidence=0.9, graph_path=[],
                             query_type="single-fact", agent_used=["copilot"],
                             retrieval_strategy="vector", latency_ms=1,
                             supporting_detail=f"Escalate to {PII_SENTENCE}",
                             groundedness_warning=[PII_SENTENCE])
    monkeypatch.setattr(main, "run_query", _fake_run_query)
    with TestClient(main.app) as c:
        body = c.post("/query", json={"question": "who to call?"}).json()
    blob = json.dumps(body)
    for frag in RAW_FRAGMENTS:
        assert frag not in blob, f"raw PII '{frag}' in API response"


def _read_log(name):
    with open(os.path.join(settings.AUDIT_DIR, name)) as f:
        return f.read()


def test_audit_logs_are_redacted():
    log_high_stakes_query(query=f"LOTO for C-202? {PII_SENTENCE}", confidence=0.5,
                          confidence_label="Medium", escalated=True)
    log_injection_attempt(chunk_id="c", doc_id="d", file_name="f.txt",
                          text_preview=PII_SENTENCE, matched_patterns=[], llm_reasoning=PII_SENTENCE)
    blob = _read_log("escalation_audit.jsonl") + _read_log("injection_audit.jsonl")
    for frag in RAW_FRAGMENTS:
        assert frag not in blob, f"raw PII '{frag}' written to audit log"
