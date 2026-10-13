# Cerebra — Interview Answers v2 (after the security-hardening fixes)

**Source of truth:** branch `fix/security-hardening` at commit `d469bcd`. Every claim cites `file:line` in the fixed code.

**Numbers:** only figures from [`EVAL_RESULTS.md`](EVAL_RESULTS.md) (generated at `d469bcd`) or from test runs. Anything else is marked **not measured**.

**State when this was written:** `pytest` gives 87 passed, 8 xfailed (the xfails are documented gaps). The real-server smoke test, `scripts/smoke_test.py` with a stub OpenAI server, passed 10/10.

> **Honesty tip.** If he asks how you found and fixed this much in one night, say you red-teamed your own repo with an AI coding assistant and drove the fixes yourself, and that you can defend each one. Section 6 exists so that last part is true. Don't let him discover it some other way.

---

## 1. What I fixed last night

| # | Fix | Before (audit finding) | After | Commit | Regression test (old code → new) |
|---|---|---|---|---|---|
| 1 | Graph query safety | LLM-written Cypher ran in a **write-capable** session as admin. No validation, LIMIT or timeout. | `READ_ACCESS` session; validator rejects writes, CALL, LOAD CSV and multi-statement queries; LIMIT clamped to 20 or less; 5 s timeout; optional least-privilege read user | `c308a95` | `test_fix01_graph_query_safety.py`: 14 fail → 16 pass |
| 2 | Write auth + rate limit | `/ingest`, the webhook and `/eval/run` were **anonymous**. Upload filenames were unsanitised. | API key (Bearer or X-API-Key, constant-time compare, fails closed); 10 writes/min per key+IP; basename-only filenames | `dc20b77` | `test_fix02_write_auth.py`: 7 fail → 9 pass |
| 3 | Graph sees only clean text | Graph extractor got the **raw** document, including chunks the scanner blocked | Extractor gets only chunks with no injection signal; no clean text means no extraction | `063ab8d` | `test_fix03_…`: 3 fail → 3 pass |
| 4 | Never return flagged chunks; abstain | Flagged chunks returned when nothing else matched; agents answered from model memory on empty context | Only explicitly scanned-clean chunks are returned; unscanned counts as untrusted; new `abstain` node makes no LLM call | `53705b3` | `test_fix04_…`: 4 fail → 4 pass |
| 5 | Confidence | Scale bug capped the copilot at **0.696**, so "High" was unreachable. Specialists were hard-coded at 0.80 / 0.78 / 0.75. | Reranker keeps raw cosine and orders by RRF; one shared `compute_confidence()` for every agent; High reachable (cosine 0.95 → 0.965) | `f81ba40` | `test_fix05_…`: 7 fail → 7 pass |
| 6 | Real human-in-the-loop | "Escalation" was a banner next to an answer the user had already received | High-stakes answers **withheld**; LangGraph `interrupt_before=["release"]` plus SQLite checkpointer; reviewer approve/edit/reject API; decisions audited | `e51859d` | `test_fix06_…`: 9 fail → 9 pass (incl. approve after simulated restart) |
| 7 | PII | Unspaced Aadhaar and lowercase PAN missed; `+91 98765 43210` → `[REDACTED PHONE]0`; answers and logs unredacted | Fixed patterns; answers, supporting detail, warnings, citations, reviewer view and **every audit record** redacted | `76a991f` | `test_fix07_…`: 6 fail → 12 pass |
| 8 | Injection-scanner hardening | Zero-width, homoglyph, base64 and full-width text all evaded the regex. **The canonical "Ignore all previous instructions" never matched** (pattern bug). | NFKC, invisible-character stripping, homoglyph mapping and base64 decoding before matching; override patterns fixed; the LLM classifier sees the de-obfuscated text | `036b158` | `test_fix08_…`: 9 fail → 12 pass; 7 known gaps pinned as strict xfails |
| 9 | Dedup | Fingerprint cache committed as `{}` while the store held 3–4 copies of 5 files; SHA-256 can't see edited copies | File SHA stored in every chunk, so the store is the source of truth; atomic, merged cache writes; MinHash near-duplicate filter (Jaccard ≥ 0.7) | `33cf4b3` | `test_fix09_…`: 3 fail → 4 pass (1 original + 20 edited copies → 2 chunks or fewer) |
| 10 | Rebuild committed store | 626 chunks, **none ever scanned**; 358 were duplicates | Offline rescan with no re-embedding: **626 → 268 chunks**, 0 flagged, compacted, 15 fingerprints | `f913214` | `test_fix10_…`: 2 fail → 3 pass |
| 11 | Eval | 3 of 5 ground truths not in the corpus; Ragas scored 200-character snippets; no results | 7-question benchmark grounded in the corpus; real contexts; `security_eval.py` → `EVAL_RESULTS.md` with a baseline | `ed31ec6` | `test_fix11_…`: 3 fail → 3 pass |
| 12 | Spreadsheets | `.csv` and `.xls` crashed `/ingest` with a 500; chunks lost their headers | CSV via stdlib; header row repeated in every chunk; `.xls` → clear error | `c120431` | `test_fix12_…`: 4 fail → 4 pass |
| 13 | `/query` rate limit | Found **after fix 6**: anonymous `/query` plus held answers meant anyone could flood reviewers | 30 queries/min per IP | `d469bcd` | `test_fix13_…`: old code accepted 40/40 rapid calls → 429 after the limit |

Supporting commits: `82d5087` adds an end-to-end smoke test of the real server with a stub OpenAI. `9ac89a7` makes that smoke test run on a temp copy of the store.

### The 60-second version (say this)

> "Before this interview I red-teamed my own system the way I'd expect you to. I found seventeen places where my claims were ahead of the code, and last night I fixed thirteen of them. Each fix has a regression test that the old code doesn't pass.
>
> The two I'd lead with are blast-radius fixes. First, graph retrieval executed LLM-written Cypher in a write-capable session as admin. It's now read-only, validated, bounded and timed out. Second, ingestion was anonymous; it now needs a key and is rate limited.
>
> Then trust fixes. High-stakes answers used to be shown with a warning banner. Now they're actually withheld behind a LangGraph interrupt with a persistent checkpointer until a reviewer approves them. Poisoned chunks no longer reach the knowledge graph, and if nothing trusted is retrieved, the system abstains.
>
> The scanner fixes surprised me most. The regex never matched the canonical 'ignore all previous instructions', and one zero-width character beat it. On my probe set it went from 2 of 16 to 9 of 16, with zero false positives on the corpus.
>
> What's still open is access control on the read side, and data going to OpenAI unredacted. I'll tell you how I'd do both."

---

## 2. Still not fixed (say these before he finds them)

| Gap | Evidence | How I'd address it |
|---|---|---|
| **No read-side authentication or per-user access control.** `/query`, `/answer/{id}` and `/graph/stats` are open; `session_id` is ignored; `role_tag` is always "general" and never filtered. | `main.py:61,119`, `ontology.py:51` | OIDC user identity → roles. Enforce them as a Chroma `where` filter and **on every hop** in Cypher (a per-node ACL predicate in the templates). Filter at retrieval, not on the answer. |
| **Company data leaves the boundary unredacted** (chunks, whole documents, images and context go to OpenAI) | `pipeline.py:59-66` (embeddings), `document_parsers.py:260-285` (vision) | A zero-retention / enterprise agreement or an in-VPC model. Redact before embedding where retrieval doesn't need the identifiers. |
| **Injection detection is still regex-first.** It misses Hindi, French, paraphrase, verifier-targeted text, plain links and split instructions (7/16 probes). The LLM classifier sees only regex hits and fails open. | `EVAL_RESULTS.md`, `tests/test_known_gaps.py`, `injection_scanner.py:198` | A small multilingual classifier on **every** chunk. Scan the assembled context per query. Fail closed for high-stakes. |
| **The groundedness verifier is a general LLM reading attacker text.** It pools all context, fails open, and doesn't check claim-to-citation. | `groundedness.py:75-107` | A narrow NLI model on one claim and one cited chunk at a time; fail closed. |
| **The HITL trigger is still a keyword list**, so paraphrases bypass it. Reviewers aren't notified. The reviewer key is shared, so reviewer names are self-declared. No SLA. | `severity.py:19-42`, `supervisor.py:440-447`, `main.py:156` | Also trigger on retrieved document types (SOP, permit) and answer content; per-reviewer SSO; notifications plus SLA and escalation; a priority queue. |
| **PII:** names, employee IDs, DOB and bank details aren't detected (4/14 probes leak) | `EVAL_RESULTS.md`, `test_known_gaps.py` | NER (Presidio or spaCy) plus custom recognisers for employee IDs. Apply the same treatment to `Person` nodes in the graph. |
| **Confidence is uncalibrated** (bands at 0.72 / 0.52 cosine) | `base.py:45-73`, `config.py:74-75` | Labelled correctness on the benchmark → reliability diagram and ECE → fit the mapping. Add verifier and self-consistency signals. |
| **Graph writes:** LLM-supplied labels are interpolated into Cypher; node properties are last-writer-wins; no entity resolution; extraction stops at 12,000 characters | `writer.py:76-77`, `pipeline.py:199` | An ontology allowlist for labels; provenance per property; entity resolution (normalised tags plus fuzzy match). |
| **Online metrics not measured:** retrieval hit rate, groundedness pass rate, p50 latency | `EVAL_RESULTS.md` | `python -m backend.eval.security_eval --online` with a key. |
| **Ops:** no LLM timeouts, `max_tokens` or cost budgets; rate limits are in-process; default Neo4j password and unrestricted APOC in compose | `base.py:102-110`, `security.py:42`, `config.py:18` | Gateway rate limits (Redis), per-user budgets, timeouts on every call, secrets management. |
| **The read-only guarantee isn't tested against a live Neo4j.** The tests use a mocked driver and assert the session mode, validator and timeout. | `test_fix01_graph_query_safety.py` | Add a Neo4j testcontainer test that tries a write in a `READ_ACCESS` session and expects `Neo.ClientError.Statement.AccessMode`. |

---

## 3. Ownership (claim only your own work)

Ownership by file header. Git can't separate authorship further, because the original code arrived in one commit (`05d09f8 Update codebase`).

| Area | Owner per header | Files |
|---|---|---|
| Ingestion, parsing, graph writer | **You (Vaibhav)** | `pipeline.py:9`, `extractor.py:7`, `document_parsers.py:3`, `writer.py:3` |
| Guardrails (injection, groundedness, severity, PII, audit) | **No header.** Commit `02c3e90 refactor(guardrails)` is from your GitHub account. **Confirm you wrote them before claiming.** | `backend/guardrails/*` |
| Supervisor graph, copilot, maintenance agent, all retrieval, eval pipeline | **Mohit** | `supervisor.py:3`, `copilot.py:3`, `maintenance.py:4`, `classifier.py:3`, `vector_search.py:3`, `graph_search.py:3`, `reranker.py:3-5`, `eval_pipeline.py:3` |
| Compliance and lessons-learned agents, frontend | **Kavyansh** | `compliance.py:3`, `lessons_learned.py:3`; frontend per the `api.ts:2` comment |
| Shared contracts (no single owner) | Team | `ontology.py` ("do not change without team agreement"), `base.py`, `main.py`, `config.py` |

### What you changed in Mohit's files tonight (describe exactly this)
| File | Commit | Change |
|---|---|---|
| `retrieval/graph_search.py` | `c308a95` | Validate generated Cypher with the new `cypher_guard.py`; use the read driver; `READ_ACCESS` session; `neo4j.Query(timeout=…)` (lines 10-11, 64-73, 115-119). |
| `retrieval/vector_search.py` | `53705b3` | Return only chunks with `injection_flagged is False`, instead of falling back to flagged chunks (line 56). |
| `retrieval/reranker.py` | `f81ba40` | Removed the 0.6/0.4 score weights; `final_score` = the item's raw score; order by RRF (lines 38, 61, 77-83). |
| `agents/copilot.py` | `f81ba40` | Confidence moved to the shared `compute_confidence`, with `_score_confidence` kept as an alias (lines 66, 83-84). |
| `agents/maintenance.py` | `f81ba40` | `0.80 if context else 0.45` → `compute_confidence(context)` (line 48). |
| `agents/supervisor.py` | `53705b3`, `f81ba40`, `e51859d`, `ed31ec6` | `abstain` node and routing; `_pick_primary` instead of max-confidence; `release` node with `needs_human_review`, the checkpointer, `interrupt_before`, `get_supervisor`, `submit_review`, pending responses; `retrieved_contexts` on responses. |
| `eval/eval_pipeline.py` | `ed31ec6` | Benchmark imported from `benchmark.py`; Ragas given full retrieved contexts instead of citation snippets. |
| `retrieval/classifier.py` | none | Unchanged. |

### What you changed in Kavyansh's files tonight
| File | Commit | Change |
|---|---|---|
| `agents/compliance.py`, `agents/lessons_learned.py` | `f81ba40` | Hard-coded 0.78 / 0.75 → `compute_confidence(context)` (lines 52 and 51). |
| `frontend/src/lib/api.ts` | `dc20b77`, `e51859d` | Upload sends `NEXT_PUBLIC_INGEST_API_KEY` (marked demo-only); `status`, `review_id` and `getReviewedAnswer()` added. |
| `frontend/src/components/ChatInterface.tsx` | `e51859d` | Polls held answers every 5 s and swaps in the released answer. |

### New files you added tonight (yours)
`backend/api/security.py`, `backend/retrieval/cypher_guard.py`, `backend/review/queue.py`, `backend/ingestion/dedup.py`, `backend/eval/{benchmark,probes,security_eval}.py`, `scripts/{rescan_store,smoke_test,fake_openai}.py`, and everything under `tests/`.

**Phrasing rule.** For the query path, say "our supervisor, which Mohit built" and "I added X to it". For ingestion and the fixes, say "I".

---

## 4. Facts, interview answers and red-team table (re-answered on the fixed code)

### PART 1 — Facts I must know cold

1. **Agents and routing.** Unchanged, apart from confidence and selection.
   - The copilot always runs; maintenance, compliance and lessons_learned are added by keyword (`supervisor.py:471-485`) and run in parallel via `asyncio.gather` (`supervisor.py:282`).
   - **No agent has tools.** All of them get the same trusted context, capped at 6,000 characters (`base.py:13-42`, `base.py:102-110`).
   - The primary answer is the first matched specialist, otherwise the copilot (`supervisor.py:488-490`, `331`). Previously it was the max of hard-coded confidences.
   - `prior_outputs` is always empty, because the agents run once in parallel (`supervisor.py:270-280`).

2. **State, reducers, checkpointer.**
   - `SupervisorState` TypedDict (`supervisor.py:157-184`), now with `review_status` and `review_decision` (lines 183-184).
   - **Still no reducers** (whole-state returns).
   - **Checkpointer:** `AsyncSqliteSaver` on `CHECKPOINT_DB_PATH` (`supervisor.py:567-574`, `config.py:57`), with one compiled graph per event loop. Every query runs on its own `thread_id` (a uuid4), which doubles as the `review_id` (`supervisor.py:664`).
   - `aiosqlite` is pinned to 0.20.0, because LangGraph 0.1.x calls `Connection.is_alive`, which 0.21+ removed (`requirements.txt`).

3. **Path through the graph.**
   1. `classify`; off-topic goes to END (`supervisor.py:532-542`).
   2. `retrieve`, which routes to `abstain` if nothing trusted came back (`supervisor.py:537-543`, `246-260`).
   3. `dispatch`, `synthesize`, then `guardrails`.
   4. **A deterministic edge** routes high-stakes runs to `release` (`supervisor.py:548-552`).
   5. Compilation uses `interrupt_before=["release"]` (`supervisor.py:558`).

   No LLM decides whether verification or review happens.

4. **Injection detection.** Runs per chunk, after OCR and vision (`pipeline.py`, scan before embed).
   - **Normalisation** (`injection_scanner.py:108-145`): NFKC; drop Unicode Cf; homoglyph map; base64 segments decoded up to two levels deep. Then 19 regexes (`PATTERN_VERSION 2.1`, line 46), with override patterns fixed (line 51).
   - **LLM classifier:** only on regex hits; it receives the de-obfuscated view (`injection_scanner.py:220`); it fails open (line 198).
   - **Outcomes:** confirmed → dropped and audited. Regex-flagged → stored as `injection_flagged=True`, never retrieved (`vector_search.py:56`), never sent to the graph (`pipeline.py:185`, `199`).

5. **Groundedness.** Unchanged.
   - Input: one GPT-4o call on the answer plus pooled context; output is a per-claim status (`groundedness.py:75-107`).
   - Caps: confidence at 0.75 for any partial or unsupported claim, and 0.40 when more than 50% are (lines 110-139).
   - It fails open, and it's skipped when context is empty. Empty context now means abstain, so that path no longer produces an answer.
   - For high-stakes answers, the reviewer sees the unsupported claims (`main.py:160-180`).

6. **Escalation.**
   - **Rule:** a keyword in the question (`severity.py:19-42`), with `HITL_MODE=all` (default) or `low_confidence` (`supervisor.py:440-447`, `config.py:60`).
   - **What the user gets:** the answer is **withheld**. The user gets `status=pending_review`, a `review_id` and a pending message; no citations or confidence (`supervisor.py:670-685`). The UI polls `GET /answer/{id}` (`main.py:201`).
   - **Reviewer:** `GET /review/pending` shows the question, draft, confidence, unsupported claims and citations (`main.py:160`). `POST /review/{id}` handles approve, edit or reject (`main.py:183`).
   - **Decision handling:** each decision is claimed atomically (`queue.py:59`); a second decision gets 409. The run resumes via `aupdate_state(..., as_node="guardrails")` then `ainvoke(None)` (`supervisor.py:722-728`). A rejection fails closed (`supervisor.py:450-467`).
   - **Logging:** decisions go to `review_audit.jsonl` with reviewer, decision, outcome, note and timestamp (`supervisor.py:735`, `audit_log.py:86-92`).

7. **PII.**
   - **Patterns:** international phone consumes the whole number; Indian mobile must start 6–9; Aadhaar spaced, hyphenated or contiguous; PAN in any case (`pii.py:32-46`). They're applied in an order that avoids partial matches (`pii.py:61-67`).
   - **Applied to:** `/query` answer, supporting detail, citation note, citations and warnings (`main.py:131-145`); the reviewer view and `/answer` (`redact_obj`); every audit record (`audit_log.py:33`).
   - **Not applied to:** the vector store, the graph, or OpenAI calls.

8. **Audit logging.**
   - Files: `injection_audit.jsonl`, `escalation_audit.jsonl`, `review_audit.jsonl`, plus Neo4j `AuditLog` nodes.
   - **All JSONL records are PII-redacted** (`audit_log.py:28-38`).
   - Still not tamper-evident, and still no general query/answer log.

9. **Confidence.**
   - `compute_confidence()` (`base.py:45-73`) maps the top **raw** cosine: ≥ 0.72 → 0.85–0.99 (High); ≥ 0.52 → 0.60–0.84 (Medium); otherwise Low; graph-only context → 0.50.
   - The same function is used by all four agents (`copilot.py:66`, `maintenance.py:48`, `compliance.py:52`, `lessons_learned.py:51`). The thresholds are environment-configurable (`config.py:74-75`).
   - Not LLM self-reported. **Not calibrated.**

10. **Citations.** Unchanged: the top unique retrieved documents (`base.py:112-140`), with redacted excerpts. Not claim-level.

11. **Retrieval.**
    - Chroma top-10 with `text-embedding-3-small`; **trusted chunks only** (`vector_search.py:56`).
    - Graph via validated read-only Cypher (`graph_search.py:64-119`).
    - Fusion by **RRF, k=60** (`reranker.py:77-83`, `config.py:71`); still one chunk per doc_id.
    - Chunking: unchanged for text. Spreadsheets now chunk by row groups **with the header repeated** (`document_parsers.py:158-175`).

12. **Graph build.**
    - Two-pass LLM extraction, now over **clean chunks only** (`pipeline.py:199-204`).
    - Writer unchanged: LLM-chosen IDs, `MERGE` plus `SET n += props` (`writer.py:76-77`), and no entity resolution.

13. **OCR routing.** Unchanged (`document_parsers.py:224-325`). The OCR and vision output is now scanned with normalisation; a test hides a zero-width instruction in an image and shows it's blocked (`test_fix08_…`).

14. **Dedup.**
    - Whole-file SHA-256, **also stored in every chunk**, and checked against the store (`pipeline.py:88-89`).
    - Cache writes are atomic and merged (`document_parsers.py:66-81`).
    - Chunk-level MinHash with 64 permutations; a chunk at Jaccard ≥ 0.7 is skipped (`dedup.py`, `pipeline.py:117-151`, `config.py:68`).

15. **Access control at retrieval.** **Still none.** Write endpoints need a key; read endpoints are open and rate limited (`main.py:119`, `security.py:71-80`).

16. **Evaluation.**
    - **Tests:** 87 pass, 8 xfail.
    - **`EVAL_RESULTS.md` (offline):**
      - injection probes 2/16 → 9/16;
      - corpus false positives 0/268;
      - PII recall 7/14 → 10/14, with 5/5 non-PII strings left intact;
      - destructive Cypher blocked 11/11, with 4/4 benign queries allowed;
      - 3-word near-copies caught 53/60, 10-word copies 12/60;
      - 0/268 wrongly deduped.
    - **Online metrics:** not measured.

17. **External APIs that receive company data.** Unchanged: OpenAI (embeddings, chat, vision), Neo4j AuraDB if cloud-hosted, and Render.

---

### PART 2 — Interview questions

> Format: **Decision → Why → Trade-off → Failure mode → Next.** Ownership-aware: "I" means your own work.

#### Q1. Walk me through Cerebra end to end.
**Decision.** I owned ingestion. A file comes in through an authenticated endpoint. I check its SHA-256 against the vector store itself, then parse it: pdfplumber with Tesseract for scanned pages, row-grouped spreadsheets with the header repeated, and OCR plus GPT-4o vision for diagrams. Every chunk is normalised and scanned for injection. Confirmed attacks are dropped, near-duplicates are skipped with MinHash, and only fully clean chunks go to the knowledge-graph extractor.

On the query side, our LangGraph supervisor, which Mohit built, retrieves only chunks the scanner cleared. If nothing trusted comes back, it abstains. Otherwise it runs the agents, checks groundedness, and for safety-critical questions it pauses at an interrupt until a human reviewer releases the answer.
**Why.** Trust decisions happen once at ingestion, and the expensive human check only on high-stakes answers.
**Trade-off.** Held answers wait on a person.
**Failure mode.** Read access isn't per-user yet.
**Next.** Identity-scoped retrieval.

- **Evidence:** `main.py:224-238`, `pipeline.py:81-204`, `document_parsers.py:158-325`, `injection_scanner.py:108-157`, `vector_search.py:56`, `supervisor.py:537-558`, `664-685`
- **Gap:** no read-side access control; data goes to OpenAI.

#### Q2. Why 4 agents and not one agent with tools?
**Decision.** Mohit and Kavyansh designed the split: a general copilot plus maintenance, compliance and lessons-learned specialists, chosen by keyword.
**Why.** Each specialist prompt carries a different analysis frame.
**Trade-off.** I'll be straight: they're specialists in prompt only. No tools, and the same context for all of them. One thing I did fix: the specialists used to report hard-coded confidences, so they won every comparison regardless of evidence. Now every agent computes confidence with the same function over the same context. Because confidence can't distinguish them any more, the primary answer is chosen explicitly: the first matched specialist, otherwise the copilot.
**Failure mode.** Keyword routing misses paraphrases.
**Next.** Either one agent with a routed prompt, or a real split: per-agent retrieval filters, so compliance sees only regulations and audits, plus a synthesizer that merges outputs.

- **Evidence:** `supervisor.py:471-490`, `base.py:45-73`, `maintenance.py:48`, `compliance.py:52`, `lessons_learned.py:51`
- **Gap:** no tools, no per-agent data scoping, no merge.

#### Q3. Why LangGraph over AutoGen, CrewAI or a plain LangChain agent?
**Decision.** The supervisor graph is Mohit's. What I added last night shows why LangGraph fits. When a question is high-stakes, a conditional edge routes the run to a `release` node. The graph is compiled with `interrupt_before=["release"]` and a SQLite checkpointer, so the run pauses and its state is persisted. A reviewer's decision is written into that thread's state and the run resumes. I also added an abstain branch.
**Why.** Both gates are explicit edges decided by code, not by a model choosing its next step. In a free-form agent loop, injected text could steer the model around a check.
**Trade-off.** It's still a mostly linear graph with no reducers, and the version we pin (0.1.14) has only static interrupts, not the newer `interrupt()` function.
**Failure mode.** The verifier node still fails open.
**Next.** Fail closed on high-stakes questions, and use `Send` fan-out so agents are traced individually.

- **Evidence:** `supervisor.py:440-467`, `548-558`, `711-735`
- **Gap:** no reducers; static interrupts only.

#### Q4. How do you compute confidence, and is it calibrated?
**Decision.** Confidence comes from retrieval strength, not from the model rating itself. One function takes the top raw cosine similarity and maps it into bands. Groundedness can only lower it.
**Why.** Self-reported confidence is poorly calibrated.
**Trade-off.** It isn't calibrated either. I found a scale bug: the reranker multiplied cosine by 0.6 before the confidence bands were applied, so nothing could ever reach "High" (the ceiling was 0.696). The specialists also had hard-coded confidences. I fixed both, and a test now pins that a strong match reaches the High band.
**Failure mode.** The band thresholds are heuristics and were never fitted to data.
**Next.** Label correctness on the grounded benchmark; combine similarity, the verifier's supported-claim ratio and self-consistency; check with a reliability diagram and ECE.

- **Evidence:** `base.py:45-73`, `reranker.py:38,61,77-83`, `config.py:74-75`, `test_fix05_confidence.py`
- **Gap:** uncalibrated.

#### Q5. How do citations work, and how do you know they're real?
**Decision.** Citations are the top distinct documents in the trusted context, with redacted excerpts, so every citation is a real document that was actually retrieved and passed the injection scan.
**Why.** The model can't invent a source.
**Trade-off.** It's provenance, not claim attribution. Groundedness checks claims against pooled context, so it catches invented facts but not a real source credited with something only another source said.
**Failure mode.** A cited document may not have contributed anything.
**Next.** Per-sentence source markers, an NLI check of each claim against only its cited chunk, and dropping citations nobody referenced.

- **Evidence:** `base.py:112-140`, `groundedness.py:88`
- **Gap:** unchanged.

#### Q6. You accepted extra latency. How much, and was it worth it?
**Decision.** I measured the non-LLM layers. Per chunk or call at p50: the injection scan is 0.25 ms, MinHash 1.5 ms, PII redaction 0.08 ms and Cypher validation 0.01 ms. These are single-machine timings that vary a little from run to run. So the deterministic trust layers are effectively free. The real cost is one extra GPT-4o call per answer, for groundedness, plus the human review on high-stakes answers, which is minutes, not milliseconds.
**Why it's worth it.** That human delay applies only to safety-critical questions, where a wrong answer is the expensive outcome.
**Trade-off / honest gap.** I haven't measured end-to-end p50 with and without the verifier, because that needs live model calls. The script supports it with `--online`.
**Next.** Run it, then put a cheap NLI check in front of the LLM verifier.

- **Evidence:** `EVAL_RESULTS.md` (local guardrail cost table), `security_eval.py`
- **Gap:** online latency not measured.

#### Q7. What happens when the groundedness check fails?
**Decision.** Confidence is capped at 0.75 if any claim isn't supported, and at 0.4 with a Low label if more than half aren't. For a normal question, the answer is shown with a warning. For a high-stakes question, the answer is held regardless, and the reviewer sees exactly which claims failed. If retrieval returns nothing trusted, we abstain before any answer is generated.
**Why.** Safety answers get a human; the rest get a visible downgrade.
**Trade-off.** Non-safety answers with unsupported claims are still shown.
**Failure mode.** The verifier fails open on errors.
**Next.** Abstain when more than half the claims are unsupported, and fail closed for high-stakes.

- **Evidence:** `groundedness.py:85-139`, `main.py:160-180`, `supervisor.py:246-260`
- **Gap:** fail-open; no abstain on a grounding failure.

#### Q8. What counts as high-stakes, and who decides?
**Decision.** A deterministic rule decides: one of 20 safety keywords in the question. In the default mode every such answer is withheld; there's also a mode that holds only answers not labelled High.
**What each side sees.** The user gets "pending review" plus an ID and polls for the result. The reviewer sees the question, the draft, the confidence, the unsupported claims and the citations, then approves, edits or rejects. Each decision is claimed once and logged with the reviewer and a timestamp. A rejection fails closed.
**Why a rule.** A poisoned document can't argue its way out of a keyword match.
**Trade-off.** Paraphrases bypass it. And because the reviewer key is shared, the reviewer name in the log is self-declared.
**Next.** Also trigger on retrieved document types and answer content; per-reviewer SSO; notifications and an SLA.

- **Evidence:** `severity.py:19-42`, `supervisor.py:440-467`, `670-685`, `711-735`, `queue.py:59`, `main.py:156-220`
- **Gap:** keyword trigger; shared key.

#### Q9. How did you evaluate the system?
**Decision.** Two parts.
- **Regression tests:** one per fix, built from my audit's probe inputs. 87 pass, and 8 known gaps are pinned as strict expected failures.
- **A security eval** scored against a fair baseline, the original patterns copied verbatim. On my probe sets:
  - injection detection went from 2 of 16 to 9 of 16, with 0 of 268 corpus chunks falsely flagged;
  - PII recall went from 7 of 14 to 10 of 14;
  - destructive Cypher blocked went from 0 to 11 of 11;
  - near-copy detection catches 53 of 60 lightly edited copies, but only 12 of 60 heavier edits.

**Why.** My RL study taught me not to trust a number without a fair baseline.
**Trade-off.** These are small, hand-built probe sets, not a benchmark. Retrieval hit rate and groundedness pass rate need live calls and aren't measured yet. I also rebuilt the benchmark so every ground truth exists in the corpus.
**Next.** Run `--online`, then measure end-to-end injection success rate.

- **Evidence:** `EVAL_RESULTS.md`, `backend/eval/security_eval.py`, `backend/eval/benchmark.py`, `tests/`
- **Gap:** online metrics not measured.

#### Q10. What would you change to put this in production?
**Decision.**
1. **Read-side identity and access control** at retrieval, including per-hop graph filters. That's the biggest remaining gap.
2. **Keep data in boundary:** zero-retention or in-VPC models.
3. **Secrets and ops:** move keys and the Neo4j password to a secret manager; actually provision the read-only Neo4j user I documented; rate limits at the gateway in Redis; timeouts and budgets on every LLM call.
4. **Detection:** a semantic classifier on every chunk, plus an NLI verifier.
5. **Tracing and the attack suite in CI:** the probes already exist as tests.

**Why.** Blast radius first, model quality second.

- **Evidence:** `main.py:119`, `config.py:18-24`, `security.py:42`
- **Gap:** all open.

#### Q11. What's Cerebra's blast radius today?
**Who does it act as?** One service identity. Graph reads use a read session and can use a least-privilege user.

**What can it reach?** Every trusted chunk, for anyone who can reach `/query`. That's the gap I'd name first.

**Which trust boundaries does it cross?** Company documents go to OpenAI. The graph may sit in AuraDB.

**What can it do?** At query time, now genuinely read-only:
- Generated Cypher runs in a read session, must pass a validator that rejects every write keyword, CALL and LOAD CSV, and is bounded and timed out.
- All writes need a key and are rate limited.
- Safety answers can't reach a user without a human.

**Before last night** the answer to "what can it do" was "possibly delete the graph". I fixed that first.

- **Evidence:** `graph_search.py:64-119`, `cypher_guard.py:22-67`, `security.py:27-90`, `main.py:119,224,260,342`
- **Gap:** no per-user reach limits.

#### Q12. If I gave Cerebra tools that send email or write to a database, what changes?
**Decision.** It would complete the lethal trifecta: private data, untrusted document content, and an outbound channel.
**What I'd do.** I've already applied the pattern I'd use to the one write-capable path I had, the Cypher runner. The model now only proposes, and code validates and executes with least privilege. For email:
- the agent that reads untrusted documents never holds the send tool;
- it emits a typed request that privileged code checks against a recipient allowlist;
- every irreversible action goes through the same interrupt-and-review gate I built for high-stakes answers.

**Trade-off.** Autonomy and reviewer fatigue.
**Next.** Templates instead of free-form actions.

- **Evidence:** `cypher_guard.py`, `supervisor.py:548-558`
- **Gap:** n/a (hypothetical).

---

### PART 3 — Red-team table (was / now)

| # | Attack | Was | Now | Evidence | Say this |
|---|---|---|---|---|---|
| 1 | Instruction hidden in a diagram or image | Partly | **Partly (better)** | OCR and vision text is normalised and scanned (`test_fix08` image test); the graph only gets clean chunks (`pipeline.py:199`) | "Image text is scanned after OCR and vision with de-obfuscation, and flagged text can't reach the graph, but detection is still regex-first." |
| 2 | Obfuscation: base64, other language, zero-width, homoglyphs | Not handled | **Partly** | Zero-width, homoglyph, full-width and base64 now caught; Hindi and French missed (`EVAL_RESULTS.md`) | "I normalise before matching, so encoding tricks fail, but other languages still pass. That needs a multilingual classifier." |
| 3 | Injection split across two chunks | Partly | Partly | Unchanged; strict xfail in `test_known_gaps.py` | "Per-chunk scanning misses it. Next is an assembled-context scan per query." |
| 4 | Poisoned doc tells the groundedness checker the answer is supported | Not handled | **Not handled** (mitigated for high-stakes) | Verifier unchanged (`groundedness.py`); high-stakes answers still go to a human (`supervisor.py:548`) | "The checker is injectable. For safety questions a human now sits behind it; the fix is a narrow NLI verifier." |
| 5 | Poisoned source, so the answer is grounded in a lie | Not handled | **Partly** | Uploads need a key and are rate limited (`main.py:224`); no source trust ranking; node properties last-writer-wins (`writer.py:76-77`) | "Uploading now needs a credential, but I don't rank sources by trust yet, and the graph lets the latest upload overwrite facts." |
| 6 | 20 near-duplicate copies | Not handled | **Mostly handled** | MinHash; 1 original + 20 edited copies → 2 chunks or fewer (`test_fix09`); 88% of 3-word edits, 20% of 10-word (`EVAL_RESULTS.md`) | "Light edits are caught. Heavy paraphrase isn't. Per-uploader quotas are next." |
| 7 | Exfiltration via markdown image or link | Partly | Partly | `![…](http` flagged at ingestion; UI renders plain text; plain links missed | "No markdown rendering means no image beacon, but I don't sanitise links server-side yet." |
| 8 | Unauthorised documents, incl. via graph hops | Not handled | **Not handled** | `main.py:119` open; `role_tag` unused | "This is my biggest open gap: no per-user access control, and the graph would need checks on every hop." |
| 9 | PII the redactor misses | Not handled | **Partly** | Indian IDs fixed; answers and logs redacted; names, IDs, DOB and bank details still leak (4/14) | "Regex now covers Aadhaar, PAN and phones everywhere output leaves the backend. Names need NER." |
| 10 | Flooding the human review queue | N/A (no queue) | **Partly** | The queue exists now; `/query` limited to 30/min per IP (`security.py:71-80`); no global cap or prioritisation | "Building the queue created this surface, so I rate-limited the open endpoint. A distributed flood would still need a global cap and prioritisation." |
| 11 | PII in audit logs | Not handled | **Handled (regex-level)** | `audit_log.py:33` redacts every record | "Every audit record is redacted before it's written. The NER caveat still applies." |
| 12 | Injection steering an agent into a loop or runaway cost | Partly | **Partly (better)** | DAG with no tools; Cypher LIMIT and timeout; write and query rate limits; no LLM timeouts or budgets | "Loops are impossible by construction and graph queries are bounded, but I don't cap tokens or spend per user yet." |

---

## 5. Real numbers only

Everything below comes from `EVAL_RESULTS.md` at `d469bcd` or from test and smoke runs on this branch. **Don't quote anything else.**

| Metric | Baseline (`02c3e90` patterns) | Now |
|---|---|---|
| Injection probes flagged (regex layer) | 2/16 | 9/16 |
| Corpus chunks falsely flagged | 0/268 | 0/268 |
| PII redaction recall (probe set) | 7/14 | 10/14 |
| Non-PII left intact | 4/5 | 5/5 |
| Destructive Cypher blocked / benign allowed | 0/11 / 4/4 | 11/11 / 4/4 |
| 3-word / 10-word edited copies caught | 0/60 / 0/60 | 53/60 / 12/60 |
| Distinct chunks wrongly deduped | n/a | 0/268 |
| Store size | 626 chunks (358 duplicates, 0 scanned) | 268 chunks, all scanned |
| Copilot confidence ceiling | 0.696 (High unreachable) | 0.965 at cosine 0.95 |
| p50 CPU cost: scan / MinHash / redact / Cypher check | n/a | 0.25 / 1.48 / 0.08 / 0.01 ms (one machine; varies run to run) |
| Tests | none | 87 pass, 8 strict xfail |
| Retrieval hit rate, groundedness pass rate, end-to-end p50 | **not measured** | **not measured** |
| Confidence calibration (ECE) | **not measured** | **not measured** |

---

## 6. How each fix works (so you can defend it)

### Fix 1 — Read-only, validated graph queries (`c308a95`)
**What changed.** Generated Cypher now passes three layers before it runs:
1. `validate_cypher()` blanks out strings and comments, then requires a read clause at the start (MATCH, WITH, UNWIND or RETURN). It rejects any write or admin keyword, any CALL, LOAD CSV and multi-statement queries (`cypher_guard.py:22-67`).
2. It clamps every LIMIT to 20 and appends one if missing.
3. It runs in a `READ_ACCESS` session with a 5-second query timeout (`graph_search.py:115-119`).

Optional `NEO4J_READ_USERNAME` lets reads use a reader-role user.

**Why it works.** Defence in depth. The validator stops the obvious cases before they reach the database. The read session makes the server itself refuse writes. A reader-role user means even a bypass of both has no write privilege. The LIMIT and timeout bound cost.

**He'll ask:** *"Regex validation of a query language? I can bypass that."*
**Answer:** "Probably, and that's why it isn't the control I rely on. The control is the read session plus the reader role, which the server enforces. The validator is there so bad queries never reach the database and get logged. The real next step is to stop generating free-form Cypher at all: the LLM picks from a few parameterised query templates. I'll also be honest that I tested the session mode with a mocked driver, not against a live Neo4j."

### Fix 2 — API keys and rate limits on writes (`dc20b77`)
**What changed.** A FastAPI dependency reads `Authorization: Bearer` or `X-API-Key` and compares it with `hmac.compare_digest`. If no key is configured, writes are refused with a 503. A sliding window allows 10 writes per minute per (key, IP). Upload filenames are reduced to their basename (`security.py`, `main.py:224-238`).

**Why it works.** Anonymous poisoning becomes credentialed and throttled. Constant-time comparison avoids timing leaks. Failing closed means a misconfigured deployment is safe, not open. The basename rule stops `../../` path traversal.

**He'll ask:** *"A static shared key isn't identity. And your frontend ships it to the browser."*
**Answer:** "Agreed on both. The browser key is labelled demo-only in the code. Production would be user SSO, with the backend doing uploads under per-user tokens, so every document has an accountable uploader. That's also the hook for source-trust ranking."

### Fix 3 — Only clean text reaches the graph (`063ab8d`)
**What changed.** During the scan loop I collect only chunks with no injection signal, and the extractor gets those joined together instead of `parsed["text"]` (`pipeline.py:124`, `185`, `199-204`).

**Why it works.** The graph is permanent, shared memory. A bad fact there is reused by every later query. So the graph gets a stricter gate than the vector store: even regex-flagged chunks that the LLM cleared are excluded.

**He'll ask:** *"So flagged-but-benign content, like 'disregard the previous reading', is missing from your graph?"*
**Answer:** "Yes, deliberately. It's still in the vector store, but it's excluded from retrieval as flagged. I'm trading some recall for integrity. The fix for the recall cost is a better classifier, not a weaker gate."

### Fix 4 — Trusted-only retrieval and abstain (`53705b3`)
**What changed.** `vector_search` returns only chunks whose metadata says `injection_flagged is False` (`vector_search.py:56`), so unscanned legacy chunks count as untrusted. If retrieval yields nothing, the graph routes to an `abstain` node that returns a fixed answer without calling any agent (`supervisor.py:246-260`, `537-543`).

**Why it works.** The old fallback, "return flagged chunks if nothing else matches", was an attacker's dream: write a chunk that's the only match for your target question. Abstaining also stops agents answering from model memory.

**He'll ask:** *"Can't I make you abstain on everything? That's a denial-of-service."*
**Answer:** "Only for questions where your poisoned chunk is the only match. Legitimate documents still answer. That trade-off is the right way round: an availability failure on a question the corpus can't answer cleanly beats a confident answer built on attacker text."

### Fix 5 — Confidence on the full range, the same for every agent (`f81ba40`)
**What changed.**
- The reranker no longer multiplies scores by 0.6/0.4. It keeps each item's raw score and orders results by Reciprocal Rank Fusion, `1/(60+rank)` (`reranker.py:77-83`).
- One `compute_confidence()` maps the top raw cosine into bands (`base.py:45-73`), and all four agents call it.
- The primary answer is now chosen explicitly (`supervisor.py:488`).

**Why it works.** The bands were written for raw cosine but were being fed `0.6 × cosine`, so the maximum was 0.696. RRF fixes the deeper problem: cosine and a path-length heuristic aren't on the same scale, so you combine **ranks**, not scores.

**He'll ask:** *"Why should cosine similarity mean confidence at all?"*
**Answer:** "It's a weak proxy, and I say so in the code and the README. It measures 'we found something relevant', not 'the answer is right'. That's why the groundedness cap sits on top and calibration is the next step. I'd fit it against labelled correctness and report expected calibration error."

### Fix 6 — Human-in-the-loop with interrupt and checkpointer (`e51859d`)
**What changed.**
- After `guardrails`, a deterministic edge routes high-stakes runs to a `release` node.
- The graph is compiled with `interrupt_before=["release"]` and an `AsyncSqliteSaver`, so the run stops and its state, including the draft, is persisted under the run's `thread_id`.
- `/query` returns `pending_review` plus the ID and withholds the answer.
- A reviewer `POST /review/{id}` claims the item atomically, writes the decision into the thread state (`aupdate_state(..., as_node="guardrails")`), and resumes with `ainvoke(None)`. `release` then applies approve, edit or reject; reject fails closed.
- Everything is logged with reviewer and timestamp.

(`supervisor.py:440-467`, `548-558`, `664-685`, `711-735`; `queue.py`; `main.py:156-220`)

**Why it works.** The answer physically doesn't exist in any response until `release` runs, and `release` can't run without a reviewer decision. The checkpointer means a restart doesn't lose pending reviews; a test approves after a simulated restart.

**He'll ask:** *"What stops a reviewer rubber-stamping, or someone forging the reviewer name?"*
**Answer:**
- **Forging:** today the reviewer key is shared, so the name is self-declared. That's my next fix: per-reviewer SSO, so identity comes from the token.
- **Rubber-stamping:** show the evidence, which I do (the unsupported claims and citations), sample-audit approvals, and keep the trigger narrow, because flooding reviewers produces rubber stamps. That's also why I rate-limited `/query`.

### Fix 7 — PII patterns and where they apply (`76a991f`)
**What changed.**
- **Patterns** (`pii.py:32-67`): Aadhaar accepts contiguous digits; PAN matching is case-insensitive; the international phone pattern consumes all its digits; Indian mobiles must start 6–9, so part numbers survive; application order prevents a `+91` number being read as an Aadhaar.
- **Coverage:** `redact_obj()` redacts recursively. It's applied to every `/query` field, the reviewer view, `/answer`, and every audit record before it's written (`audit_log.py:33`).

**Why it works.** The leaks were pattern bugs (a missing optional separator, case sensitivity, an under-consuming phone regex) plus a coverage bug (only citations were redacted). Both are fixed and pinned by tests that use the exact audit inputs.

**He'll ask:** *"You still send the raw text to OpenAI and store it in Chroma."*
**Answer:** "Yes. Redaction protects what leaves our backend. Upstream, the right control is a zero-retention agreement or an in-boundary model, plus access control on the stores. I'd only redact before embedding for identifiers retrieval never needs, because redacting everything breaks search."

### Fix 8 — De-obfuscation before scanning (`036b158`)
**What changed.** `build_scan_view()` runs before the regexes (`injection_scanner.py:108-157`):
- NFKC (full-width → ASCII);
- removes every Unicode format character (category Cf, which covers zero-width spaces and joiners, BOM and bidi controls);
- maps Cyrillic and Greek look-alikes to Latin;
- decodes base64 segments of 16+ characters that turn into readable text, up to two levels deep.

The regexes run on that view, and the LLM classifier receives it too. I also fixed the override pattern, which allowed only one of "all" or "previous", so "Ignore **all previous** instructions" never matched.

**Why it works.** Attackers target the gap between what the model reads and what the filter matches. Normalising to the model's reading closes the cheap tricks. Requiring decoded base64 to be readable text means hashes and IDs don't create false positives: 0 of 268 corpus chunks.

**He'll ask:** *"So now I write it in Hindi, or paraphrase it."*
**Answer:** "Then the regex misses it. Those cases are in my test suite as expected failures, so the gap is on record in code. Regex is the cheap first filter. The real layer is a multilingual classifier on every chunk, plus the fact that safety answers now go to a human regardless."

### Fix 9 — Persistent fingerprints and MinHash near-duplicates (`33cf4b3`)
**What changed.**
- Each chunk stores its file's SHA-256. Ingestion asks the **store** whether that file exists, so a lost cache no longer matters (`pipeline.py:88-89`).
- Cache writes are atomic (`os.replace`) and merged under a lock.
- Each chunk gets a 64-value MinHash signature over word 3-shingles. If its estimated Jaccard similarity to any stored chunk is 0.7 or more, it's skipped (`dedup.py`, `pipeline.py:117-151`).

**Why it works.** MinHash estimates set overlap. A lightly edited copy keeps most of its 3-word shingles, so its similarity stays high, while unrelated text scores near zero. I picked 0.7 from the corpus: distinct chunks max out at 0.61, and 3-word-edited copies have a median of 0.88.

**He'll ask:** *"Why not SimHash? And how does this scale?"*
**Answer:** "I tried SimHash first and measured it. On 800-character chunks a 3-word edit moved fingerprints 3 to 15 bits, and repetitive table chunks collided at zero, so it was both too strict and too loose. MinHash is the right tool for short-text Jaccard. Today the lookup is a linear scan; at scale I'd index signatures with LSH banding, so candidate lookup is constant-time."

### Fix 10 — Rescan the committed store (`f913214`)
**What changed.** `scripts/rescan_store.py`:
- keeps one ingestion per file;
- drops exact-duplicate chunks;
- runs the current scanner on every kept chunk (any regex hit counts as flagged, because there's no LLM pass offline);
- stamps scan, SHA and MinHash metadata;
- **compacts** the collection, then rebuilds the fingerprint cache.

It reuses the existing embeddings, so it needs no API key. The committed store went from 626 to 268 chunks.

**Why it works.** Retrieval now treats unscanned data as untrusted, so legacy data has to be re-scanned. Compaction matters because deleted HNSW entries still occupied top-k slots: before compaction a top-10 query returned only 7.

**He'll ask:** *"Offline you can't run the LLM classifier, so what about borderline chunks?"*
**Answer:** "They're marked flagged, so they're never retrieved. That fails safe. There happened to be none in this corpus. A production rescan would queue flagged chunks for the classifier."

### Fix 11 — Grounded eval and security eval (`ed31ec6`)
**What changed.** There's a 7-question benchmark in which each answer has a phrase verified to be present in its source document (a test checks it). The Ragas script now gets the full retrieved contexts. `security_eval.py` scores the probe sets against the original patterns as a baseline and writes `EVAL_RESULTS.md`.

**Why it works.** The old ground truths referenced equipment that doesn't exist in the corpus, so scores were noise. A baseline built from the same probe set makes the before/after comparison fair.

**He'll ask:** *"Your probes are the attacks you already knew about. Isn't that circular?"*
**Answer:** "Partly, yes. That's why the misses are reported too: 7 of 16 still get through. The next step is held-out attacks from garak or PyRIT, plus an end-to-end attack success rate that asks whether the injection changed the answer, not just whether the filter fired."

### Fix 12 — CSV and header-preserving spreadsheet chunks (`c120431`)
**What changed.** CSV is parsed with the standard library's `csv` module (dialect sniffing, BOM-safe). Spreadsheets are chunked by row groups, with the sheet name and header row repeated in every chunk. `.xls` returns a clear error instead of a 500 (`document_parsers.py:154-226`).

**Why it works.** A table row without its header is meaningless to an embedding. "P-150 | 3.1 | normal" says nothing until you know the columns.

**He'll ask:** *"What about aggregation questions over a 10,000-row sheet?"*
**Answer:** "Chunked retrieval is the wrong tool for that. I'd load the table into DuckDB and let a tool answer with SQL. That's a structured-data path, not RAG."

### Fix 13 — `/query` rate limit (`d469bcd`)
**What changed.** A per-IP sliding-window limit of 30 queries per minute on `/query` (`security.py:71-80`).

**Why it works.** Holding answers made each high-stakes query cost reviewer time, so an open endpoint became a way to flood reviewers.

**He'll ask:** *"So you created a new attack surface with your own fix?"*
**Answer:** "Yes, and I found it by re-running my red-team table after the change. That's the point of doing it. Per-IP limits don't stop a distributed flood, so the real fix is authenticated `/query`, per-user quotas, and a global cap on the queue that degrades to 'try later' instead of growing without bound."

---

## Don't say
- "Hallucination-free", "fully secure", or that any layer is unbeatable.
- "Escalation notifies a human". It holds the answer; nobody is notified.
- Any end-to-end latency figure, retrieval hit rate or groundedness pass rate. They're not measured.
- That you built the supervisor or the retrieval stack. Mohit did; say you hardened them.
