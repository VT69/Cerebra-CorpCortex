"""
Security & trust-layer evaluation. Writes EVAL_RESULTS.md.

Offline metrics (no API key needed) are always computed, each against a
baseline: the original v2.0 scanner/PII patterns copied verbatim from commit
02c3e90, so before/after numbers come from the same probe set.

Online metrics (retrieval hit rate, groundedness pass rate, end-to-end p50
latency) need a real OPENAI_API_KEY and are only run with --online; without
it they are reported as "not measured".

Usage:
  python -m backend.eval.security_eval            # offline only
  python -m backend.eval.security_eval --online   # + benchmark via run_query
"""
import argparse
import asyncio
import random
import re
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import chromadb

from backend.config import settings
from backend.eval import probes
from backend.eval.benchmark import BENCHMARK
from backend.guardrails.injection_scanner import PATTERN_VERSION, scan_text_for_injection
from backend.guardrails.pii import redact_pii
from backend.ingestion import dedup
from backend.retrieval.cypher_guard import UnsafeCypherError, validate_cypher

# ── Baselines: original code at commit 02c3e90 (verbatim patterns) ───────────
_V20_INJECTION = [re.compile(p, re.IGNORECASE) for p in [
    r"ignore\s+(all\s+|previous\s+|the\s+)?(above\s+|prior\s+)?instructions",
    r"disregard\s+(the\s+)?(above|system\s+prompt|previous)",
    r"forget\s+(all\s+|your\s+)?(previous\s+|prior\s+)?(instructions|rules|context)",
    r"you\s+are\s+now\s", r"act\s+as\s+(if\s+)?you\s+(are|have)", r"pretend\s+(you\s+are|to\s+be)",
    r"roleplay\s+as\b", r"\bDAN\b.*do\s+anything\s+now", r"new\s+instructions\s*:", r"system\s+prompt\s*:",
    r"<\/?(system|instructions?)>", r"\[INST\]", r"<<\s*SYS\s*>>", r"reveal\s+your\s+(system\s+)?prompt",
    r"(print|show|display|repeat|output)\s+(your\s+)?(system\s+)?(prompt|instructions|rules)",
    r"what\s+(is|are)\s+your\s+(system\s+)?(prompt|instructions|rules)", r"respond\s+only\s+with",
    r"translate\s+(the\s+)?(above|previous)\s+(to|into)", r"!\[.*?\]\(https?://",
]]
_V1_PII = [
    (re.compile(r"\b[\w.\-+]+@[\w.\-]+\.\w{2,}\b", re.IGNORECASE), "[REDACTED EMAIL]"),
    (re.compile(r"(?:\+\d{1,3}[\s\-.]?\(?\d{2,4}\)?[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}"
                r"|\(\d{2,4}\)[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}|\b\d{5}[\s\-.]?\d{5}\b)"), "[REDACTED PHONE]"),
    (re.compile(r"\b\d{4}[\s\-]\d{4}[\s\-]\d{4}\b"), "[REDACTED AADHAAR]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[REDACTED PAN]"),
]


def _v20_flags(text: str) -> bool:
    return any(p.search(text) for p in _V20_INJECTION)


def _v1_redact(text: str) -> str:
    for p, repl in _V1_PII:
        text = p.sub(repl, text)
    return text


def _leaks(redacted: str, value: str) -> bool:
    """True if the PII value (or, for numbers, any 4+ digit run of it) survives."""
    if value in redacted:
        return True
    if re.search(r"\]\d|\d\[REDACTED", redacted):  # partial redaction, e.g. "[REDACTED PHONE]0"
        return True
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 6:
        tail = re.sub(r"\D", "", redacted)
        return digits[-4:] in tail or digits[:4] in tail
    return False


def _pct(n, d):
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "n/a"


def _corpus() -> list[str]:
    col = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR).get_collection(settings.CHROMA_COLLECTION_NAME)
    return col.get(include=["documents"])["documents"]


def _p50_ms(fn, items, repeat=3):
    times = []
    for _ in range(repeat):
        for it in items:
            t = time.perf_counter()
            fn(it)
            times.append((time.perf_counter() - t) * 1000)
    return statistics.median(times), sorted(times)[int(len(times) * 0.95)]


def offline_metrics() -> dict:
    corpus = _corpus()
    out = {"corpus_chunks": len(corpus)}

    # 1. Injection detection on the audit probe set
    rows = []
    for name, text in probes.INJECTION_ATTACKS:
        rows.append((name, _v20_flags(text), scan_text_for_injection(text)["flagged"]))
    out["injection_rows"] = rows
    out["injection_v20"] = sum(r[1] for r in rows)
    out["injection_new"] = sum(r[2] for r in rows)
    out["injection_total"] = len(rows)
    out["injection_fp_corpus_v20"] = sum(_v20_flags(t) for t in corpus)
    out["injection_fp_corpus_new"] = sum(scan_text_for_injection(t)["flagged"] for t in corpus)

    # 2. PII redaction recall on the probe set (+ precision on non-PII)
    rows = []
    for name, text, value in probes.PII_PROBES:
        rows.append((name, not _leaks(_v1_redact(text), value), not _leaks(redact_pii(text), value)))
    out["pii_rows"] = rows
    out["pii_v1"] = sum(r[1] for r in rows)
    out["pii_new"] = sum(r[2] for r in rows)
    out["pii_total"] = len(rows)
    out["pii_nonpii_v1"] = sum(_v1_redact(t) == t for t in probes.PII_NON_PII)
    out["pii_nonpii_new"] = sum(redact_pii(t) == t for t in probes.PII_NON_PII)
    out["pii_nonpii_total"] = len(probes.PII_NON_PII)

    # 3. Near-duplicate detection (MinHash) on real corpus chunks
    rng = random.Random(0)
    sigs = [dedup.minhash(t) for t in corpus]
    out["dedup_fp"] = sum(
        any(dedup.similarity(sigs[i], sigs[j]) >= settings.NEAR_DUP_JACCARD for j in range(len(sigs)) if j != i)
        for i in range(len(sigs)))
    for edits in (3, 10):
        sample = rng.sample(range(len(corpus)), 60)
        caught = 0
        for i in sample:
            words = corpus[i].split()
            for _ in range(edits):
                words[rng.randrange(len(words))] = rng.choice(["revised", "noted", "unit", "per"])
            caught += dedup.similarity(sigs[i], dedup.minhash(" ".join(words))) >= settings.NEAR_DUP_JACCARD
        out[f"dedup_catch_{edits}"] = (caught, len(sample))

    # 4. Cypher guard
    destructive = [
        "MATCH (n) DETACH DELETE n", "CREATE (x:Equipment {id:'evil'}) RETURN x",
        "MERGE (x:Person {id:'a'}) RETURN x", "MATCH (e) SET e.p = 1 RETURN e",
        "MATCH (a:AuditLog) REMOVE a.operation RETURN a", "DROP CONSTRAINT c",
        "CALL apoc.load.json('https://evil.example') YIELD value RETURN value",
        "CALL dbms.security.createUser('x','y',false)",
        "LOAD CSV FROM 'https://evil.example/x.csv' AS row RETURN row",
        "MATCH (n) RETURN n; MATCH (m) DETACH DELETE m",
        "MATCH (n) FOREACH (x IN [1] | CREATE (:Evil)) RETURN n",
    ]
    benign = [
        "MATCH (e:Equipment)-[:CONNECTED_TO]->(o) RETURN e, o",
        "MATCH (e:Event)-[:CAUSED_BY]->(q:Equipment {tag:'P-101'}) RETURN e LIMIT 10",
        "MATCH (d:Document) WHERE d.title CONTAINS 'DELETE' RETURN d",
        "OPTIONAL MATCH (p:Person) RETURN count(p)",
    ]

    def _blocked(q):
        try:
            validate_cypher(q)
            return False
        except UnsafeCypherError:
            return True
    out["cypher_blocked"] = (sum(_blocked(q) for q in destructive), len(destructive))
    out["cypher_allowed"] = (sum(not _blocked(q) for q in benign), len(benign))

    # 5. Local (non-LLM) guardrail latency
    out["lat_scan"] = _p50_ms(scan_text_for_injection, corpus)
    out["lat_minhash"] = _p50_ms(dedup.minhash, corpus)
    out["lat_redact"] = _p50_ms(redact_pii, corpus)
    out["lat_cypher"] = _p50_ms(validate_cypher, benign * 50)
    return out


async def online_metrics() -> dict:
    """Run the benchmark through the real pipeline (needs OPENAI_API_KEY)."""
    from backend.agents.supervisor import get_review_state, run_query
    rows = []
    for item in BENCHMARK:
        t = time.perf_counter()
        resp = await run_query(item["question"])
        latency = (time.perf_counter() - t) * 1000
        contexts = resp.retrieved_contexts
        grounded = None
        if resp.status == "pending_review":
            _, state = await get_review_state(resp.review_id)
            contexts = [c.get("text", "") for c in state.get("reranked_context", [])]
            grounded = not state.get("groundedness_warning")
        elif resp.status == "answered":
            grounded = not resp.groundedness_warning
        hit = any(item["must_contain"] in c for c in contexts)
        rows.append({"q": item["question"], "status": resp.status, "hit": hit,
                     "grounded": grounded, "latency_ms": latency, "label": resp.confidence_label})
    return {"rows": rows}


def render(off: dict, on: dict | None) -> str:
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    L = [
        "# Cerebra — Evaluation Results",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} at commit `{commit}` "
        f"by `python -m backend.eval.security_eval`. Scanner `PATTERN_VERSION {PATTERN_VERSION}`.",
        "",
        "**Baseline** = the original code at commit `02c3e90` (patterns copied verbatim into the eval). "
        "**Now** = this commit. Same probe sets for both (`backend/eval/probes.py`).",
        "",
        "## Summary",
        "",
        "| Metric | Baseline | Now |",
        "|---|---|---|",
        f"| Injection probes flagged by regex layer | {_pct(off['injection_v20'], off['injection_total'])} | "
        f"{_pct(off['injection_new'], off['injection_total'])} |",
        f"| Corpus chunks falsely flagged as injection | {off['injection_fp_corpus_v20']}/{off['corpus_chunks']} | "
        f"{off['injection_fp_corpus_new']}/{off['corpus_chunks']} |",
        f"| PII redaction recall (probe set) | {_pct(off['pii_v1'], off['pii_total'])} | "
        f"{_pct(off['pii_new'], off['pii_total'])} |",
        f"| Non-PII left intact (precision probes) | {_pct(off['pii_nonpii_v1'], off['pii_nonpii_total'])} | "
        f"{_pct(off['pii_nonpii_new'], off['pii_nonpii_total'])} |",
        f"| Destructive Cypher blocked before Neo4j | 0/{off['cypher_blocked'][1]} (no validation) | "
        f"{_pct(*off['cypher_blocked'])} |",
        f"| Benign read Cypher allowed | {off['cypher_allowed'][1]}/{off['cypher_allowed'][1]} | "
        f"{_pct(*off['cypher_allowed'])} |",
        f"| 3-word-edited chunk copies caught as near-duplicates | 0/{off['dedup_catch_3'][1]} (SHA-256 only) | "
        f"{_pct(*off['dedup_catch_3'])} |",
        f"| 10-word-edited chunk copies caught | 0/{off['dedup_catch_10'][1]} | {_pct(*off['dedup_catch_10'])} |",
        f"| Distinct corpus chunks wrongly treated as near-duplicates | n/a | "
        f"{off['dedup_fp']}/{off['corpus_chunks']} |",
        "",
        "## Injection probes (regex layer, before any LLM)",
        "",
        "| Probe | Baseline v2.0 | Now |",
        "|---|---|---|",
        *[f"| {n} | {'flagged' if a else '**missed**'} | {'flagged' if b else '**missed**'} |"
          for n, a, b in off["injection_rows"]],
        "",
        "The remaining misses (non-English, paraphrase, verifier-targeted, plain link, split halves) are "
        "pinned as strict xfails in `tests/test_known_gaps.py`. They need a semantic/multilingual "
        "classifier on every chunk and an assembled-context scan; regex cannot catch them.",
        "",
        "## PII probes",
        "",
        "| Probe | Baseline | Now |",
        "|---|---|---|",
        *[f"| {n} | {'redacted' if a else '**leaked**'} | {'redacted' if b else '**leaked**'} |"
          for n, a, b in off["pii_rows"]],
        "",
        "Names, employee IDs, dates of birth and bank details need NER / custom recognisers; not done.",
        "",
        "## Local guardrail cost (CPU, per call; corpus chunks, 3 passes)",
        "",
        "| Step | p50 ms | p95 ms |",
        "|---|---|---|",
        *[f"| {name} | {off[k][0]:.3f} | {off[k][1]:.3f} |" for name, k in [
            ("Injection scan (normalise + base64 + 19 regexes)", "lat_scan"),
            ("MinHash signature (64 perms)", "lat_minhash"),
            ("PII redaction", "lat_redact"),
            ("Cypher validation", "lat_cypher")]],
        "",
        "These are the non-LLM trust layers. The LLM calls (injection classifier on regex hits, "
        "groundedness verifier per answer) dominate real latency and are measured only in the online run.",
        "",
        "## Online metrics (real LLM)",
        "",
    ]
    if on:
        rows = on["rows"]
        answered = [r for r in rows if r["grounded"] is not None]
        lat = sorted(r["latency_ms"] for r in rows)
        L += [
            f"- Retrieval hit rate (expected passage in trusted context): {_pct(sum(r['hit'] for r in rows), len(rows))}",
            f"- Groundedness pass rate: {_pct(sum(bool(r['grounded']) for r in answered), len(answered))}",
            f"- End-to-end p50 latency: {statistics.median(lat):.0f} ms (n={len(lat)})",
            f"- Held for human review: {sum(r['status'] == 'pending_review' for r in rows)}/{len(rows)}",
            "", "| Question | Status | Hit | Grounded | Label | ms |", "|---|---|---|---|---|---|",
            *[f"| {r['q']} | {r['status']} | {r['hit']} | {r['grounded']} | {r['label']} | {r['latency_ms']:.0f} |"
              for r in rows],
        ]
    else:
        L += [
            "**Not measured.** Retrieval hit rate, groundedness pass rate and end-to-end p50 latency "
            "require real embeddings and GPT-4o calls; no `OPENAI_API_KEY` was available when this file "
            "was generated. Run `python -m backend.eval.security_eval --online` with a key to fill this "
            f"section ({len(BENCHMARK)} benchmark questions, all with ground truths present in the corpus: "
            "`backend/eval/benchmark.py`).",
        ]
    L += ["", "## Not measured anywhere yet", "",
          "- Confidence calibration (reliability diagram / ECE): needs labelled correctness on real answers.",
          "- Injection success rate end-to-end (does an injected chunk change the answer?): needs a live model.",
          "- Reviewer workload / time-to-decision for held answers."]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--online", action="store_true")
    ap.add_argument("--out", default="EVAL_RESULTS.md")
    args = ap.parse_args()
    off = offline_metrics()
    on = asyncio.run(online_metrics()) if args.online else None
    Path(args.out).write_text(render(off, on))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
