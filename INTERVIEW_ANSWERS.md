# Cerebra — Interview Answers (grounded in the code)

Prepared for: GenAI Agent Engineer interview, Grafyn AI (Anshuman Bal).
Source of truth: this repository at commit `02c3e90`. Every factual claim has a `file:line` reference. Where I ran something to check behaviour, it says **(verified by running the code)**. Those probes imported the real `backend/guardrails/*`, `backend/retrieval/reranker.py` and `backend/agents/copilot.py` modules with a stubbed config, or read `data/chroma/chroma.sqlite3` read-only. No repo code was changed.

How to use this file:
1. Read **Resume vs code mismatches** first. He will find these.
2. Learn **Part 1** cold. Those are the facts behind every answer.
3. Practise **Part 2** out loud. Each answer is about 45–60 seconds.
4. Use **Part 3** when he tries to break it live.

---

## Resume vs code mismatches (read this first)

| # | Resume / README claim | What the code actually does | Evidence | How to say it |
|---|---|---|---|---|
| 1 | "Orchestrating **4 specialist agents**" | One general `copilot` always runs. Three "specialists" (maintenance, compliance, lessons_learned) are added by **keyword match on the question**. None of them have tools. All of them get the **same** retrieved context. Synthesis keeps **one** output: the one with the highest confidence. The three specialists return **hard-coded** confidences (0.80 / 0.78 / 0.75), and the copilot can never score above 0.696, so **whenever a specialist runs, its answer wins and the copilot's is discarded**. The specialists' outputs are never merged. | `supervisor.py:401-415`, `supervisor.py:288`, `maintenance.py:48`, `compliance.py:52`, `lessons_learned.py:51`, `copilot.py:83-106` | "It's one router plus three prompt-specialised agents. Today it behaves more like prompt routing than a team: one answer wins." |
| 2 | "Escalation of high-stakes answers **to a human**" | No human is notified, nothing is queued, and LangGraph `interrupt` is not used. If the question contains one of 20 keywords and the confidence label is Medium or Low, the API adds a **text banner** telling the user to "verify with a qualified engineer". The answer is still shown immediately. The only thing a human could review later is a JSONL line. | `severity.py:19-63`, `supervisor.py:367-383`, `supervisor.py:466` (compiled with no checkpointer), `ChatInterface.tsx:130-132` | "Escalation today is a warning to the user plus an audit record, not a human-in-the-loop hold. Here's how I'd make it real." |
| 3 | "**PII redaction**" (implied: of the data) | Display-only regex redaction of the **200-character citation excerpts**. The **answer text, supporting detail, graph text, embeddings, everything sent to OpenAI, and the audit logs are not redacted.** The regex also misses things (see Part 1 #7). | `pii.py:1-7`, `base.py:102-104`, `pipeline.py:149-155` (raw chunk embedded) | "Redaction is at the display layer on citation snippets only. It's not before indexing, not on the answer, and not before OpenAI." |
| 4 | "**Full** audit logging" | Three narrow trails: (a) injection detections, (b) queries that contain high-stakes keywords, (c) Neo4j `AuditLog` nodes for every graph write. **Normal queries, answers, retrieved docs, uploads and who asked are not logged.** Logs hold **raw PII** (the raw query; 200-character raw chunk previews). Nothing is tamper-evident. | `audit_log.py:27-101`, `writer.py:146-177`, `pipeline.py:117-124` | "I audit security events and graph writes, not every interaction, and the logs aren't redacted or hash-chained." |
| 5 | "Groundedness verification of **every** answer" | One GPT-4o call judges the whole answer against **all retrieved context pooled together**. It **fails open** on error, is **skipped when there's no context**, and is skipped on the off-topic path. It **lowers the confidence label and adds a warning**; it never blocks, retries or abstains. It does **not** check citations. | `groundedness.py:75-107`, `groundedness.py:110-139`, `supervisor.py:455-458` | "It's an LLM-judge faithfulness check that downgrades and warns. It doesn't block and it doesn't verify claim-to-citation." |
| 6 | "Prompt-injection detection on ingested content" | Real for the **ChromaDB** path: 19 regex patterns, then an LLM confirmation on regex hits only. Confirmed chunks are dropped. But: (a) **graph extraction is fed the full raw text, including chunks the scanner blocked**; (b) chunks that were flagged but cleared **are returned anyway when they are the only hits**; (c) the classifier **fails open**; (d) **none of the 626 chunks in the committed demo vector store carry the `injection_flagged` field**, which the current pipeline always writes, so the demo store was built **before** the scanner existed; (e) user questions and Neo4j text are never scanned. | `injection_scanner.py:44-157`, `pipeline.py:112-137`, `pipeline.py:164-167`, `vector_search.py:52-56`; the demo store finding was **verified by querying the SQLite file** | "Injection scanning gates the vector store. It doesn't gate the knowledge graph, and my demo data predates it." |
| 7 | "Accepted extra latency so **risky outputs are caught before reaching the user**" | At query time nothing is caught or blocked. The answer is always returned, with a label or banner attached. The extra query-time cost is **one sequential GPT-4o verifier call**. Latency was **never measured** with and without the trust layer. | `supervisor.py:336-391`, `supervisor.py:519` (`latency_ms` only), no eval report in the repo (`.gitignore:16` excludes `data/eval/`) | "I accepted one extra LLM hop. I haven't measured it, and today it labels risky outputs rather than stopping them." |
| 8 | "Confidence scores" | Heuristic, not LLM self-reported. But there is a **scale bug**: the copilot's thresholds (0.72 / 0.52) were written for raw cosine scores and are applied **after** the reranker multiplies by 0.6. The copilot's maximum is therefore **0.696**, and the "High" label (≥ 0.85) is **unreachable for any retrieved answer**. The comment says "sentence-transformers", but the embeddings are OpenAI `text-embedding-3-small`. | `reranker.py:35`, `copilot.py:87-106`, `supervisor.py:297-302`, `config.py:25`; **verified by running** `rerank` + `_score_confidence` | "It's a retrieval-similarity heuristic, it's uncalibrated, and it has a scale bug I found while preparing." |
| 9 | "With **cited sources**" | The citations returned are simply the **top 5 unique retrieved documents**. They aren't tied to which claim used which source. The copilot also emits a free-text `citation_note` that nothing verifies. | `base.py:83-119`, `copilot.py:21`, `copilot.py:62` | "Citations are retrieval provenance, not claim attribution." |
| 10 | "Hybrid retrieval (ChromaDB + Neo4j **traversal**)" | Neo4j is queried by **LLM-generated Cypher** (text-to-Cypher), not by a traversal that starts from the vector hits. Results are merged by a **weighted sum of incomparable scores** (cosine × 0.6, path-length heuristic × 0.4), not by RRF. Dedup keeps **one chunk per doc_id**. | `graph_search.py:17-100`, `reranker.py:14-76`; **verified**: 5 chunks from the same doc_id → 1 kept | "Hybrid here means vector plus text-to-Cypher over a knowledge graph, fused by a weighted score. Not dense plus BM25, and not RRF." |
| 11 | "Company's PDFs, **spreadsheets** and diagrams" | `.xlsx` works. **`.csv` and `.xls` crash**, because openpyxl rejects both formats, and `/ingest` doesn't catch the exception. Spreadsheets get the generic fixed 800-character chunking with **no header repetition**. | `document_parsers.py:137-164`, `document_parsers.py:318-319`; **verified**: `InvalidFileException` for both | "xlsx only today. CSV is a known bug." |
| 12 | "Multi-modal ingestion using **GPT-4 Vision**" | The model is **`gpt-4o`** (`OPENAI_VISION_MODEL`). Vision runs only on **standalone image files** or `doc_type=pid`, with a **P&ID-specific prompt** (equipment tags and connections). Diagrams **embedded inside PDFs are ignored**. Only near-empty PDF pages get OCR'd, and with Tesseract only. | `config.py:13`, `document_parsers.py:171-274`, `document_parsers.py:110-130`, `document_parsers.py:314-315` | "GPT-4o vision on image uploads, tuned for P&IDs." |
| 13 | "SHA-256 deduplication" | Whole-file hash checked against a JSON cache. The committed cache is `{}` while the committed vector store holds **the same files ingested 3–4 times** under different doc_ids (e.g. `Calibration-Catalogue…pdf` ×4, `inspection_report_V201_2024.txt` ×4, `work_order_P101_2024.txt` ×3). | `document_parsers.py:45-65`, `pipeline.py:81-85`, `data/fingerprints.json`; **verified by querying** `chroma.sqlite3` | "File-level exact-match dedup. My own demo store shows why that isn't enough." |
| 14 | Evaluation (implied by "confidence" and "trust") | There's a Ragas script with **5 questions**. **3 of the 5 ground truths reference equipment that doesn't exist in the corpus** (K-101, P-203, V-301 / OISD-118). It passes **citation snippets** to Ragas instead of the real retrieved contexts. **No report and no tests exist.** | `eval_pipeline.py:37-63`, `eval_pipeline.py:73`; **verified**: 0 chunks contain K-101, P-203, V-301 or OISD-118 | "I scaffolded eval but don't have numbers I'd defend." |
| 15 | System is read-only / small blast radius | **Not read-only.** LLM-generated Cypher runs in a default (write-capable) Neo4j session using the admin credentials. `/ingest` and `/webhook/qms/incident` write to the knowledge base **with no authentication**. `/eval/run` spends OpenAI money, also with no auth. | `graph_search.py:103-107`, `writer.py:180-185`, `main.py:132-233`, `main.py:247-254` | Say it before he does (see Part 2 Q11). |
| 16 | "My … system" | File headers attribute ownership: `supervisor.py`, the retrieval files and `eval_pipeline.py` say "Mohit owns this file"; `compliance.py`, `lessons_learned.py` and the frontend say "Kavyansh". `pipeline.py`, `extractor.py`, `document_parsers.py` and `writer.py` say "Vaibhav owns this file". The product is also named three ways: Cerebra-CorpCortex, IndustrialIQ, NexusRAG. | `supervisor.py:3`, `pipeline.py:9`, `compliance.py:3`, `api.ts:2`, `main.py:33`, `PROJECT_REPORT.md:4` | Be precise about which parts you built: "It was a three-person build; I owned ingestion, the knowledge graph and the guardrails layer." **Adjust this to what's actually true.** |
| 17 | README: "hallucination-free enterprise reliability" | Nothing in the code can guarantee that (see #5). | `README.md:23` | Don't repeat it. If he quotes it: "That line overclaims; groundedness is a mitigation, not a guarantee." |

### Things your prep sheet's model answers say that the code contradicts
- **Q1 sheet:** "redacted for PII, then indexed." **Wrong.** Redaction happens only on citation excerpts at response time (`base.py:102-104`).
- **Q1 sheet:** "routes the question to 4 specialist agents … hybrid search." The router is **keyword-based** (`supervisor.py:401-415`). The copilot always runs, and the others are optional.
- **Q2 sheet:** "each agent only gets the tools and data it needs." **False today.** No agent has tools, and all of them get identical context (`supervisor.py:227-239`).
- **Q3 sheet:** "LangGraph gives me checkpointing and interrupt … exactly what human escalation needs." Neither is used (`supervisor.py:466`; grep finds no `checkpoint` or `interrupt`).
- **Q5 sheet:** "the model must cite IDs … groundedness verifies each claim against the chunk it cites." **Neither is true.** Context is labelled `[Source N | file | score]` (`base.py:28`), but nothing requires or parses those labels, and the verifier pools all the context (`groundedness.py:88`).
- **"Explain LangGraph's state model … add_messages"**: `add_messages` is imported but unused (`supervisor.py:23`). There are no reducers, and every node returns the whole state (`{**state, ...}`).

---

# PART 1 — Facts I must know cold

### 1. The 4 agents, routing, and what each can access
- **Copilot** (always runs): general Q&A. JSON output `{answer, supporting_detail, citation_note}` (`copilot.py:11-29`). Confidence comes from retrieval scores (`copilot.py:66`, `83-106`).
- **Maintenance/RCA**: 5-Why analysis, maintenance recommendations with priority. Free-text output, confidence fixed at **0.80** (0.45 if there's no context) (`maintenance.py:8-55`).
- **Compliance**: gaps against OISD, PESO, Factory Act, CPCB and BIS, with severity. Fixed **0.78** / 0.40 (`compliance.py:7-59`).
- **Lessons learned**: patterns across incidents. Fixed **0.75** / 0.40 (`lessons_learned.py:7-58`).
- **Routing:** substring keywords on the lowercased question (`supervisor.py:401-415`). Maintenance triggers on "maintenance, repair, failure, rca, root cause, work order, downtime, mtbf". Compliance on "compliance, regulation, oisd, peso, factory act, audit, gap, non-conformance". Lessons on "lesson, incident, near miss, failure pattern, repeat, recurring, history".
- **Execution:** `asyncio.gather` inside one LangGraph node (`supervisor.py:221-252`), not LangGraph fan-out.
- **Synthesis:** `primary = max(outputs, key=confidence)` (`supervisor.py:288`). Citations are merged from all outputs; answers are not merged.
- **Tools and data:** **No agent has tools.** Each makes one `chat.completions` call with no `tools` (`base.py:73-81`). All agents receive the **same** reranked context, capped at 6,000 characters (`base.py:13-42`). `prior_outputs` is always empty because the agents run once, in parallel, starting from `specialist_outputs=[]` (`supervisor.py:229`, `501`). In practice, **agents never see each other's output**.

### 2. LangGraph state, reducers, checkpointer
- `SupervisorState` is a `TypedDict` with 21 fields (`supervisor.py:135-159`): question, query_type, query_reasoning, vector_hits, graph_hits, reranked_context, retrieval_strategy, specialist_outputs, final_answer, supporting_detail, citation_note, citations, confidence, confidence_label, retrieval_path, graph_path, agents_used, start_time, is_high_stakes, groundedness_warning, escalation_notice.
- **Reducers: none.** No `Annotated[...]` fields. `add_messages` is imported but unused (`supervisor.py:23`). Every node returns `{**state, ...}`, i.e. it overwrites the full state.
- **Checkpointer: none.** It's `graph.compile()` with no arguments (`supervisor.py:466`). No `interrupt`, no thread IDs. `session_id` arrives at the API and is ignored (`main.py:54`, `main.py:111`).
- LangGraph version: `langgraph==0.1.14` (`requirements.txt:14`).

### 3. Are security checks graph nodes the LLM can't skip? Exact path
Path (`supervisor.py:445-466`, `473-536`, `main.py:102-129`):
1. `POST /query`, then `run_query(question)`.
2. **Small-talk short-circuit** in plain Python, before the graph runs (`supervisor.py:480-491`).
3. `classify` node: an LLM picks single-fact, multi-hop, aggregation or off-topic, and a keyword check sets `is_high_stakes` (`supervisor.py:166-193`).
4. **Conditional edge:** off-topic goes to `END`, which **skips guardrails** and returns a canned refusal (`supervisor.py:455-460`).
5. `retrieve`: embed, query Chroma, and possibly run text-to-Cypher against Neo4j, then rerank (`supervisor.py:196-218`).
6. `dispatch`: select agents by keyword and run them in parallel (`supervisor.py:221-252`).
7. `synthesize`: pick the max-confidence output, merge citations (`supervisor.py:255-333`).
8. `guardrails`: groundedness check, confidence cap, escalation notice, audit (`supervisor.py:336-391`).
9. `END`, then the response is returned.

The guardrails node sits on a **fixed edge** (`supervisor.py:463`). No LLM decides whether it runs. The only LLM-influenced branch is the off-topic classification, and that path returns a hard-coded string. **Caveats:** the verifier **fails open** on exceptions (`groundedness.py:104-107`) and is **skipped when context is empty** (`groundedness.py:85`). Injection scanning is **not** in the query graph at all; it runs only at ingestion.

### 4. Prompt-injection detection
- **Method:** two layers. Layer 1 is **19 regex patterns** (verified count), versioned `PATTERN_VERSION = "2.0"` (`injection_scanner.py:42-77`). Layer 2 is a GPT-4o JSON classifier, **called only when the regex fires**, on the first 2,000 characters (`injection_scanner.py:92-131`, `config.py:51`).
- **When:** after parsing. That means **after OCR and vision extraction**, because `parse_document` runs first (`pipeline.py:91`, then the scan at `pipeline.py:113`).
- **Granularity:** per **chunk** (`pipeline.py:109-113`).
- **On a flag:**
  - LLM confirms → the chunk is **not embedded** and an audit record is logged (`pipeline.py:115-127`).
  - Regex hit but the LLM clears it → the chunk is embedded with `injection_flagged=True` and logged as cleared (`pipeline.py:130-147`).
  - At retrieval, flagged chunks are filtered out **unless no clean hits exist, in which case they're returned** (`vector_search.py:52-56`).
- **Gaps:**
  - Graph extraction runs on `parsed["text"][:12000]`, the **raw full text, including blocked chunks** (`pipeline.py:164-167`).
  - The classifier fails open (`injection_scanner.py:128-131`).
  - The user's question is never scanned.
  - Graph text is never scanned.
  - **Verified:** zero-width characters, Cyrillic homoglyphs, base64, Hindi, French, paraphrased instructions, text aimed at the verifier, plain markdown links, and an instruction split across two chunks are **all missed** by the regex. The legitimate industrial sentence "Disregard the previous pressure reading…" **is** flagged; the LLM layer exists to clear exactly that kind of false positive.
- **Defence at query time:** retrieved text is wrapped in `<retrieved_context>` tags with a "data, not instructions" preamble (`base.py:34-42`).

### 5. Groundedness
- **Input:** `final_answer` (only the primary agent's `answer` field, not `supporting_detail`) plus **all** reranked context texts joined with `---`. That can be up to 20 items, even though the agent itself only saw 6,000 characters (`supervisor.py:351-358`, `groundedness.py:88-89`).
- **Model:** GPT-4o, temperature 0, JSON mode (`groundedness.py:92-100`).
- **Output:** `{claims:[{claim, status: supported|partial|unsupported}], overall_grounded, unsupported_claims}` (`groundedness.py:55-60`).
- **Thresholds** (`groundedness.py:110-139`, `config.py:52-54`):
  - all claims supported → no change;
  - any partial or unsupported → confidence capped at **0.75**, and High becomes Medium;
  - more than **50%** of claims unsupported (counting partials) → capped at **0.40**, label Low.
- **Claim-to-chunk?** **No.** It checks claims against the **pooled** context. It never looks at citations or IDs.
- **On failure:** the answer is still returned. The confidence is capped. `groundedness_warning` (the list of claims) goes into the API response, and the UI shows a **generic** amber note: "Some details … could not be fully verified" (`ChatInterface.tsx:148-159`). **No retry, no abstain, no escalation.** On a verifier error it **fails open** and reports the answer as grounded (`groundedness.py:104-107`).
- Interaction worth knowing: specialist confidences are already ≤ 0.80, so the 0.75 cap almost never changes the **label**. Only the more-than-50% case visibly downgrades it.

### 6. High-stakes escalation
- **Rule:** `is_high_stakes(question)` is true if any of **20 keywords** appears as a substring of the **question**: lockout, tagout, loto, shutdown, permit, hazard, gas leak, evacuation, confined space, hot work, pressure release, emergency, compliance violation, safety procedure, explosion, fire hazard, toxic, asphyxiation, blowdown, relief valve (`severity.py:19-26`). On top of that, the post-groundedness label must be **Medium or Low** (`severity.py:28`, `61-62`).
- Because "High" is unreachable for retrieved answers (see #9), **every keyword match escalates**. In effect the rule is keyword-only.
- **Human notified?** No. **Queue?** No. **LangGraph interrupt?** No (`supervisor.py:466`).
- **User sees:** an orange banner above the answer: "⚠ This question involves a safety-critical procedure… verify with a qualified engineer or safety officer before acting on it" (`severity.py:30-34`, `ChatInterface.tsx:104-114`). The answer is shown at the same moment.
- **Audit:** every high-stakes query goes to `./data/escalation_audit.jsonl`, whether or not it escalated (`supervisor.py:376-383`, `audit_log.py:86-101`).
- **Verified bypasses:** "How do I isolate energy on conveyor C-202 before servicing?" and "Is it OK to open the stave cooling line during a hydrogen spike?" are **not** flagged. "What permits exist?" **is**.

### 7. PII redaction
- **Method:** regex only (`pii.py:19-40`). Entity types: email, phone (with country code, with a parenthesised area code, or a 10-digit `5+5` form), Aadhaar (`dddd[ -]dddd[ -]dddd`), PAN (`[A-Z]{5}\d{4}[A-Z]`). Optional `known_names` matching is supported, but **no caller ever passes names** (`base.py:104`).
- **Where:** only on the **200-character `text_span` of each citation** (`base.py:102-104`). Not before embedding (`pipeline.py:149-155`). Not on the answer. Not on graph text. Not before OpenAI. Not before logging.
- **Indian IDs (verified):** spaced Aadhaar is redacted, but **unspaced `123456789012` is not**. Uppercase PAN is redacted, but **lowercase is not**.
- **Other misses (verified):** names ("Rajesh Sharma"), employee IDs, dates of birth, and bank or IFSC numbers are not redacted. `+91 98765 43210` becomes `[REDACTED PHONE]0`, **leaking a digit**. The false positive "Part no. 12345-67890" becomes `[REDACTED PHONE]`.
- The demo corpus contains real-looking names ("Rajesh Sharma", "Amit Patel" in `seed_demo_data.py:38,107`). `Person` nodes, with `employee_id` in the extraction schema, are stored in Neo4j unredacted (`extractor.py:34`).

### 8. Audit logging
- **`./data/injection_audit.jsonl`:** `injection_confirmed` (chunk_id, doc_id, file_name, **raw 200-character text preview**, patterns, LLM reasoning) and `injection_flagged_cleared` (`audit_log.py:45-78`).
- **`./data/escalation_audit.jsonl`:** **raw query**, confidence, label, escalated flag (`audit_log.py:86-101`).
- **Neo4j `AuditLog` nodes** for every node and edge upsert: operation, entity, source_doc_id, pass_id, extractor, timestamp (`writer.py:146-177`).
- Writes are thread-locked appends that never raise (`audit_log.py:27-37`).
- **PII in logs:** yes. Raw queries and raw chunk previews.
- **Tamper-evident:** no. They're plain append-only files, with no hashing. The Neo4j audit nodes sit in the **same database, under the same admin credentials that LLM-generated Cypher runs with** (#15). On Render's free plan the local disk is ephemeral, so the JSONL files are lost on redeploy (`render.yaml:7`).
- **Not logged:** ordinary queries, answers, retrieved chunks, uploads, the uploader's identity, and groundedness failures (unless the query was high-stakes).

### 9. Confidence score
- **Not LLM self-reported.** That was a deliberate change (`copilot.py:64-66`, `GUARDRAILS.md:36`).
- **Copilot:** a piecewise mapping of the top reranked `final_score` (`copilot.py:83-106`).
- **Specialists:** constants (#1).
- **Then:** groundedness caps (#5). Label thresholds are High ≥ 0.85 and Medium ≥ 0.60 (`supervisor.py:297-302`).
- **Bug (verified by running):** `final_score = cosine × 0.6` (`reranker.py:35`), but the copilot thresholds assume raw cosine. So cosine 1.0 → **0.696** (the maximum), cosine 0.90 → 0.624, cosine 0.80 → 0.552 (Low), and the best possible graph-only result → 0.477. **No retrieved answer can be labelled High.**
- **Not calibrated.** No reliability diagram or ECE exists anywhere.

### 10. Citations
- Every context item is shown to the agent as `[Source i | vector/graph | score=…]` (`base.py:28`). Note the label uses `item["source"]` (vector or graph), **not the filename**.
- The returned `citations` are built from the **context list**, not from the answer. They're the first 5 unique `file_name`s, with redacted 200-character spans (`base.py:83-119`). Then they're merged across agents, deduplicated by title, and capped at 8 (`supervisor.py:305-328`).
- Graph items have empty metadata, so they come out as "Unknown Document" (`reranker.py:59`, `base.py:94`).
- Copilot's `citation_note` is free text and unverified (`copilot.py:21`).
- **Verification:** none. Nothing checks that a cited document supports a claim, or even that the model used it.

### 11. Retrieval, merging, embeddings, chunking
- **Embeddings:** OpenAI `text-embedding-3-small`, 1,536 dimensions; Chroma with cosine distance (`config.py:25`, `pipeline.py:48-63`, verified in `chroma.sqlite3`).
- **Vector:** top-k 10 (`config.py:43`, `vector_search.py:17-56`).
- **Graph:** runs if the classifier says multi-hop or aggregation, **or** the top raw cosine is below 0.70 (`supervisor.py:206`, `vector_search.py:59-67`).
- **Merge** (`reranker.py:14-76`):
  - vector items get `0.6 × cosine`;
  - graph items get `0.4 × max(0.3, 1 − 0.25 × (path_len − 1))`;
  - dedup by `doc_id`, which keeps **one chunk per document** (verified), or the first 100 characters of text when doc_id is empty;
  - sort, keep the top 20.
  - No RRF, no cross-encoder.
- **Chunking** (`document_parsers.py:71-103`):
  - sop, regulation and manual: split on numbered or lettered section headers;
  - work_order: split on `WO-…`;
  - inspection: split on numbered items;
  - everything else, **including spreadsheets**: 800 characters with 100 overlap.
  - Spreadsheets are rows joined with `|` under a `## Sheet:` header, then generic chunks, **no header repetition** (`document_parsers.py:137-164`).
  - P&ID images become **one chunk** of OCR text plus the vision JSON (`document_parsers.py:263-268`).
  - The API defaults `doc_type` to `"generic"` (`main.py:135`), and the seed script uploads everything as generic (`seed_demo_data.py:134`). **So the committed corpus is 625 generic chunks and 1 pid chunk (verified).**

### 12. How the Neo4j graph is built
- **Two-pass LLM extraction** on the first **12,000 characters** of each document (`pipeline.py:164-167`). Long PDFs are mostly not in the graph.
  - Pass 1: GPT-4o, JSON mode, fixed ontology prompt. Six node types (Equipment, Document, Parameter, Person, Regulation, Event) and eight edge types (`extractor.py:24-64`).
  - Pass 2: GPT-4o "verifier" assigns confidence and approval; facts below 0.70 are dropped (`extractor.py:70-96`, `167-219`, `ontology.py:100-105`).
- **The ontology is not enforced in code.** `NODE_TYPES` and `EDGE_TYPES` are `Literal` type hints that are never checked. LLM-supplied type strings are **interpolated into Cypher f-strings** (`writer.py:75-79`, `124-129`).
- **Entity resolution: none.** The node `id` is whatever "stable id" the LLM invents ("pump-P-101"). `MERGE` on `id` means two documents that pick the same id merge (by accident), and "P-101" vs "pump-P-101" become two nodes. `SET n += $props` means **the latest document overwrites node properties** (`writer.py:75-79`).
- **Provenance:** on **edges**, not nodes (`writer.py:109-119`).
- **Edge endpoints are `MERGE`d**, so an edge can create stub nodes (`writer.py:121-129`).
- `/webhook/qms/incident` writes `Event` and `Equipment` nodes directly, without auth (`main.py:165-233`).

### 13. OCR routing
- **Image files** (`.png .jpg .jpeg .tif .tiff .bmp`) or `doc_type=pid`: OpenCV threshold and denoise (if installed), then **Tesseract + GPT-4o vision, both**. If vision fails, it falls back to OCR-only, labelled as such. If both fail, nothing is ingested (`document_parsers.py:171-274`, `314-315`).
- **PDFs:** pdfplumber text. Tesseract runs only on pages with fewer than 50 extractable characters. **No vision for PDFs** (`document_parsers.py:110-130`).
- There's no content-based routing beyond this.

### 14. SHA-256 dedup
- **Whole file**, streamed in 8 KB blocks (`document_parsers.py:45-51`), checked against `data/fingerprints.json` (`pipeline.py:81-85`).
- Not chunk-level, not near-duplicate.
- The cache is updated only on success (`pipeline.py:226-230`).
- `/ingest` writes the file to disk **before** the dedup check, under the client-supplied filename (`main.py:142-144`).
- **The committed store holds 3–4 copies of several files** (verified), which proves the cache was reset while Chroma was not.

### 15. Access control at retrieval
- **None.** There's no authentication on any endpoint (`main.py`). `session_id` is ignored. Chroma queries have no `where` filter (`vector_search.py:34-38`).
- The ontology has a `role_tag` field ("general" | "safety-officer-only" | "admin-only") (`ontology.py:51`), but it's **always the default "general"** and **never filtered on**.
- Neo4j: the LLM writes arbitrary Cypher, so **any traversal can reach any node**. Shared entity nodes connect every document that mentions them.
- `Document` nodes store the server `file_path` (`pipeline.py:188-194`).

### 16. Evaluation that exists
- `backend/eval/eval_pipeline.py`: 5 questions, Ragas answer_relevancy, faithfulness and context_recall; average latency and confidence; push to Langfuse. Exposed through unauthenticated `/eval/run` and `/eval/report` (`main.py:236-254`).
- **Problems:**
  - 3 of 5 ground truths aren't in the corpus (verified);
  - contexts are the 200-character citation snippets, not what the model saw (`eval_pipeline.py:73`);
  - no report is committed (`data/eval/` is gitignored, `.gitignore:16`).
- **Tests:** none (no test files in the repo).
- **Latency:** `latency_ms` is returned per request (`supervisor.py:519`), but no measurements are recorded.
- **Real numbers I can quote:**
  - 626 chunks in the demo store, 5 files duplicated 3–4×;
  - 19 injection regexes, 20 escalation keywords;
  - copilot confidence ceiling 0.696;
  - 10 of 13 injection probe strings were **not** flagged by the regex: every obfuscated variant (zero-width, homoglyph, base64, Hindi, French), a paraphrase, a verifier-targeted note, a plain markdown link, and both halves of a split instruction. The 3 that were flagged: the plain attack, a markdown image, and a legitimate industrial sentence (a false positive).

### 17. External APIs that receive company data
- **OpenAI**, for nearly everything:
  - every chunk (embeddings, `pipeline.py:56-63`);
  - every query (embedding and classifier);
  - the first 12,000 characters of every document, twice (extraction passes);
  - every diagram image, as base64 (`document_parsers.py:209-233`);
  - retrieved context to each agent and to the verifier;
  - regex-flagged chunks to the classifier;
  - the question to the Cypher generator.
- **Neo4j AuraDB**, when deployed as configured (`render.yaml:15-20`): the full graph, including Person nodes.
- **Render:** hosts the API plus the Chroma and upload files on its disk.
- **Vercel:** frontend only.
- **Langfuse:** eval scores and metadata only, no text (`eval_pipeline.py:161-183`).
- No redaction happens before any of these.

---

# PART 2 — Interview questions (spoken, first person)

> Format: **Decision → Why → Trade-off → Failure mode → What I'd do next**, then Evidence and Gap. Read the bold labels silently; say the rest.

### Q1. Walk me through Cerebra end to end.

**Decision.** There are two paths. On **ingestion**, a file hits FastAPI and I SHA-256 the whole file to skip exact repeats. Then a per-type parser runs: pdfplumber for PDFs, with Tesseract on scanned pages; openpyxl for Excel; and for diagram images, OpenCV clean-up plus Tesseract and GPT-4o vision. Every chunk goes through a regex injection scan, and regex hits go to an LLM classifier. Confirmed injections are dropped and logged. Clean chunks are embedded into ChromaDB, and a two-pass LLM extractor writes entities and relationships to Neo4j with provenance on the edges. On the **query** path, a LangGraph graph classifies the question, retrieves from Chroma, and for multi-hop or weak matches also from Neo4j through LLM-generated Cypher. It runs a general copilot plus keyword-selected specialists in parallel and keeps the strongest answer. A final guardrails node then checks groundedness, caps confidence and adds a safety banner for high-stakes questions.
**Why.** Ingestion-time work is paid once per document; query-time checks sit on a fixed edge.
**Trade-off.** Two stores and lots of LLM calls.
**Failure mode.** PII redaction only happens on citation snippets at the very end, not before indexing. And the graph extractor sees the raw text even when the scanner blocked a chunk.
**Next.** Move scanning and redaction in front of both stores.

- **Evidence:** `main.py:102-162`, `pipeline.py:70-238`, `document_parsers.py:110-325`, `supervisor.py:166-466`, `base.py:102-104`, `pipeline.py:164-167`
- **Gap:** Redaction isn't before indexing. The graph bypasses the injection gate. Vision is gpt-4o, not "GPT-4 Vision". "Hybrid" is text-to-Cypher plus vector.

### Q2. Why 4 agents and not one agent with tools?

**Decision.** One general copilot always runs, and three domain specialists are added by keyword: maintenance and root cause, regulatory compliance, and lessons learned.
**Why.** Each one carries a different analysis frame: five-whys, regulation-gap severity, cross-incident patterns. Keeping them separate keeps each prompt focused.
**Trade-off.** I'll be straight. Today they're specialists in prompt only. None has tools, and they all get the same retrieved context, so I don't get least-privilege out of the split. Also, the synthesis step keeps the single highest-confidence output, and the specialists report fixed confidences above anything the copilot can score. So when a specialist runs, its answer wins and the others are discarded. It's closer to prompt routing than a team.
**Failure mode.** Keyword routing misses paraphrases. "Why did the bearing seize?" never reaches the maintenance agent.
**Next.** Either collapse it into one agent with a routed prompt, which is honestly better for most questions, or make the split real: per-agent retrieval filters, so compliance sees only regulations and audits; a synthesizer that merges outputs; and a typed, validated schema on each agent's output.

- **Evidence:** `supervisor.py:401-415`, `supervisor.py:288`, `base.py:73-81`, `maintenance.py:48`, `compliance.py:52`, `lessons_learned.py:51`, `copilot.py:83-106`
- **Gap:** No tools, no per-agent data scoping, no merge. Routing is keywords. `prior_outputs` is always empty.

### Q3. Why LangGraph over AutoGen, CrewAI or a plain LangChain agent?

**Decision.** I modelled the query path as an explicit state graph: classify, retrieve, dispatch, synthesize, guardrails, end. There's one conditional edge, for off-topic questions.
**Why.** The guardrails node sits on a fixed edge, so no model decides whether verification runs. In AutoGen or CrewAI the model chooses the next speaker or tool, and an injected document could steer it around a check. The only LLM-driven branch I have is the off-topic classifier, and that path returns a canned reply.
**Trade-off.** I'm using LangGraph lightly. There's no checkpointer, no interrupt and no reducers, and parallelism is an asyncio gather inside one node rather than graph fan-out. Today plain async Python would behave the same; the value is the explicit structure.
**Failure mode.** The guardrail node fails open. If the verifier call errors, the answer passes as grounded.
**Next.** Compile with a checkpointer, use interrupt for real human escalation, fan agents out with Send so each is traced separately, and fail closed on high-stakes questions.

- **Evidence:** `supervisor.py:445-466`, `supervisor.py:241`, `groundedness.py:104-107`
- **Gap:** No checkpointer, interrupt or reducers. `add_messages` is imported but unused (`supervisor.py:23`).

### Q4. How do you compute confidence, and is it calibrated?

**Decision.** Confidence is deliberately **not** the model rating itself. For the copilot I map the top retrieval score to a 0-to-1 range. The specialist agents use fixed values. Then the groundedness check caps it: at 0.75 if any claim isn't supported, and at 0.4 if more than half aren't.
**Why.** Self-reported LLM confidence is badly calibrated, and a model grading its own homework is the thing I was trying to avoid.
**Trade-off.** It isn't calibrated either. And while preparing I found a scale bug. The thresholds were written for raw cosine similarity, but they're applied after the reranker multiplies by 0.6. So the copilot can never exceed about 0.7, and the "High" label is unreachable for any retrieved answer.
**Failure mode.** The label tells you which agent ran more than how likely the answer is to be right.
**Next.** Build a labelled question set and combine three signals: retrieval similarity, the supported-claim ratio from the verifier, and agreement across a few samples. Fit that to correctness, then check it with a reliability diagram and expected calibration error.

- **Evidence:** `copilot.py:64-106`, `reranker.py:35`, `supervisor.py:297-302`, `groundedness.py:110-139`, `config.py:52-54`
- **Gap:** Uncalibrated. "High" is unreachable (verified). Three agents use constants. The code comment says "sentence-transformers" but the embeddings are OpenAI.

### Q5. How do citations work, and how do you know they're real?

**Decision.** Every retrieved chunk goes into the prompt with a source label. The citations I return are the top five distinct documents in the retrieved context, with a short excerpt.
**Why.** That guarantees every citation is a real document that was actually retrieved. The model can't invent a file name in the citation list.
**Trade-off.** It's retrieval provenance, not claim attribution. The model isn't required to tag which source supports which sentence, and nothing parses that. The copilot also writes a free-text citation note that nothing verifies. The groundedness check verifies claims against all retrieved context pooled together. So it catches invented facts, but **not** the case where a real source gets credit for something only another source said.
**Failure mode.** A document can appear as a citation without contributing anything.
**Next.** Require a source marker on every sentence and parse them. Verify each claim against only the chunk it cites, using a narrow NLI-style checker. Drop citations nobody referenced.

- **Evidence:** `base.py:28`, `base.py:83-119`, `copilot.py:21`, `supervisor.py:305-328`, `groundedness.py:88`
- **Gap:** No claim-to-chunk verification. Graph citations show as "Unknown Document".

### Q6. You accepted extra latency. How much, and was it worth it?

**Decision.** At query time the trust layer adds one sequential GPT-4o call, the groundedness verifier, after the answer is drafted. The severity check and PII redaction are regex and keyword matches, so they cost effectively nothing. At ingestion the injection regex runs on every chunk, and the LLM classifier runs only on chunks the regex flags.
**Why.** That puts the expensive work where it's paid once per document.
**Trade-off.** Honestly, I never measured it. Each response carries a latency field, but I didn't record p50 with and without the guardrails node. And "caught before reaching the user" overstates it: today the verifier labels and warns; it doesn't block.
**Failure mode.** I'm paying latency for a check that fails open.
**Next.** Run the benchmark set N times with the guardrails node toggled and report p50 and p95. Then cut the cost: a small NLI model first, the LLM verifier only when that's uncertain, and caching for repeated questions. The verifier can't run in parallel with generation because it needs the answer, but it can run per sentence while the answer streams.

- **Evidence:** `supervisor.py:336-391`, `supervisor.py:519`, `pipeline.py:112-127`, `injection_scanner.py:134-157`
- **Gap:** No latency numbers. Nothing is blocked at query time.

### Q7. What happens when the groundedness check fails?

**Decision.** The verifier labels each claim supported, partial or unsupported. If any aren't supported, I cap confidence at 0.75 and downgrade High to Medium. If more than half aren't, I cap at 0.4 and mark it Low. The unsupported claims go back in the API response, and the UI shows an amber "couldn't fully verify" note.
**Why.** I didn't want to silently pass a weak answer.
**Trade-off.** The answer is still shown. I don't retry and I don't abstain. Two weaker spots: if the verifier errors it fails open, and if retrieval returned nothing the check is skipped.
**Failure mode.** On a safety question, a mostly unsupported answer still reaches the user, with only a label and a banner.
**Next.** Abstain when more than half the claims are unsupported: "I couldn't find support for this in the documents." Strip unsupported sentences when it's only one or two. Fail closed on high-stakes questions. Retry once with stricter instructions. A confident wrong answer is worse than no answer.

- **Evidence:** `groundedness.py:85-107`, `groundedness.py:110-139`, `ChatInterface.tsx:148-159`
- **Gap:** No retry, abstain or block. Fail-open. The UI doesn't show which claims failed.

### Q8. What counts as high-stakes, and who decides?

**Decision.** It's a deterministic rule. The question is high-stakes if it contains one of 20 safety keywords, like lockout, LOTO, confined space, hot work, gas leak or relief valve, **and** the final confidence is Medium or Low. In practice the label is never High for retrieved answers, so it's effectively keyword-only.
**Why.** I didn't want an LLM deciding whether something is dangerous, because a poisoned document can't talk a keyword list out of firing.
**Trade-off.** What happens next is weaker than my resume suggests. The user sees an orange banner telling them to verify with a qualified engineer, and the answer is shown at the same time. No human is notified; the only reviewer artefact is an audit log line.
**Failure mode.** Paraphrase bypass. "How do I isolate energy on conveyor C-202?" isn't flagged.
**Next.**
- Trigger on the question **and** on the retrieved document types and the answer content.
- For high-stakes, hold the answer with LangGraph interrupt and tell the user "a safety officer is reviewing this" with an expected time.
- Give the reviewer the question, the draft, the cited chunks and the failed claims, with approve, edit or reject actions.

- **Evidence:** `severity.py:19-63`, `supervisor.py:170`, `supervisor.py:367-383`, `ChatInterface.tsx:104-132`
- **Gap:** There's no human in the loop. The keyword list is bypassable. Every keyword match escalates.

### Q9. How did you evaluate the system?

**Decision.** I wired a Ragas pipeline: answer relevancy, faithfulness and context recall on a benchmark set, with average latency and confidence, pushed to Langfuse.
**Why.** I wanted a repeatable number I could re-run when retrieval changed.
**Trade-off.** I don't have numbers I'd defend, and I'd rather tell you why. The set is only five questions. Three of the ground truths refer to equipment that isn't in my corpus. And I passed the citation snippets to Ragas instead of the actual retrieved context, so faithfulness is measured against the wrong text. There are no unit tests either.
**Failure mode.** A number from that setup would look rigorous and mean nothing.
**Next.** Here's the eval I'd build first:
1. Recall@k on a hand-labelled set of 50 to 100 questions, comparing vector-only, graph-only and fused.
2. Faithfulness at claim level.
3. An injection suite covering the obfuscations I already know the regex misses, reporting attack success rate.
4. PII redaction recall on a seeded set with Aadhaar, PAN and names.

My NeuroPlast RL study taught me not to trust a number without a fair baseline, so each of these comes with one.

- **Evidence:** `eval_pipeline.py:37-63`, `eval_pipeline.py:73`, `eval_pipeline.py:113-121`, `.gitignore:16`
- **Gap:** No valid eval, no tests, no measured numbers.

### Q10. What would you change to put this in production?

**Decision.** In priority order, driven by what I found reading my own code.
1. **Identity and access first.** Authenticate every endpoint, especially ingest and the QMS webhook, which currently write to the knowledge base anonymously. Carry user roles and enforce them as a Chroma metadata filter and inside every Cypher traversal step.
2. **Make the graph path read-only.** Run generated Cypher in a read-only session, under a least-privilege Neo4j user, with a query timeout. Better still, replace free-form text-to-Cypher with parameterised templates.
3. **Close the trust gaps.** Scan and redact before **both** stores. Redact before logging and before sending to OpenAI, or get a zero-retention agreement. Hash-chain the audit log.
4. **Ops.** An async ingestion queue; OpenTelemetry or LangSmith tracing; per-user rate limits and cost budgets; timeouts on every LLM call; and the attack suite from my eval running in CI on every change.

**Why.** The highest-impact issues are who can reach and change data, not model quality.
**Trade-off.** Templates lose some flexibility for ad-hoc graph questions.
**Failure mode if I skip step 1.** Everything else is moot.

- **Evidence:** `main.py:39-254`, `graph_search.py:103-107`, `writer.py:180-185`, `render.yaml:35-36`, `config.py:18`
- **Gap:** None of these exist today.

### Q11. What is Cerebra's blast radius today?

**Decision.** I'll answer in your four questions, and I'll name the worst one before you find it.
- **Who does it act as?** One service identity: one OpenAI key and the Neo4j admin user. There's no user identity at all; the session ID is accepted and ignored.
- **What can it reach?** Everything ingested, for anyone who can reach the API. CORS is a wildcard in the deployed config, and there's no retrieval-time filtering.
- **Which trust boundaries does it cross?** Company documents go to OpenAI: every chunk for embeddings, whole documents for extraction, diagram images to vision, and retrieved context on every query. The graph sits in AuraDB.
- **What can it do?** This is the one I'd flag. I'd like to say it's read-only, but it isn't. The graph retriever executes LLM-generated Cypher in a normal write-capable session, as admin. A crafted question could plausibly produce a delete. I haven't tested that live, but nothing in the code stops it. Ingest and the webhook also let anyone write to the knowledge base.

**Next.** Read-only session, a least-privilege DB user, auth, and per-user filters. That shrinks it to "read what you're allowed to, over a declared boundary".

- **Evidence:** `config.py:11-18`, `main.py:52-54`, `main.py:111`, `render.yaml:35-36`, `graph_search.py:103-107`, `pipeline.py:56-63`, `document_parsers.py:209-233`, `main.py:132-233`
- **Gap:** Not read-only. No identity or authorization. Data leaves to OpenAI unredacted.

### Q12. If I gave Cerebra tools that send email or write to a database, what changes?

**Decision.** It would complete the lethal trifecta: private data, untrusted content from uploaded documents, and an exfiltration channel. I'd point out it's already partly there, because generated Cypher can write to the graph.
**Why it matters.** Today a poisoned PDF can only change what an answer says. With email, the same PDF could tell the agent to send the compliance audit somewhere.
**Trade-off.** Every control I'd add costs autonomy:
- human approval on every irreversible action, which LangGraph interrupt is built for;
- separate, short-lived credentials per tool;
- a recipient allowlist;
- **separation**, so the agent that reads untrusted documents has no access to the send or write tools and can only emit a typed request that a privileged step validates.
**Failure mode.** Approval fatigue: reviewers rubber-stamp.
**Next.** I'd start by applying that separation to the Cypher path I already have: the LLM proposes a template ID and parameters, and code executes it read-only.

- **Evidence:** `graph_search.py:73-131`, `base.py:73-81` (agents have no tools today)
- **Gap:** The read-only claim is false today (Q11).

---

# PART 3 — Red-team table

| # | Attack | Status | Evidence | One sentence to say |
|---|---|---|---|---|
| 1 | Instruction hidden as text inside a diagram or image | **Partly** | Scan runs **after** OCR and vision on the P&ID chunk (`pipeline.py:91,113`; `document_parsers.py:263-268`), but it's regex-gated. The same raw text goes to graph extraction unscanned (`pipeline.py:166`). Images inside PDFs aren't processed at all (`document_parsers.py:117-123`). | "Image text is scanned after OCR and vision, so it doesn't skip the scanner, but the scanner is regex-first and the graph extractor still sees the raw text." |
| 2 | Obfuscation: base64, other language, zero-width, homoglyphs | **Not handled** | **Verified:** all five forms are missed by the regex, and the LLM classifier never sees them (`injection_scanner.py:134-144`). No Unicode normalisation anywhere. | "Detection is one layer, and mine is beatable by obfuscation. Next is NFKC normalisation, stripping invisible characters, decoding base64 and running a multilingual classifier on every chunk, not just regex hits." |
| 3 | Injection split across two chunks | **Partly** | Chunks are scanned independently (`pipeline.py:109-113`); **verified** that neither half is flagged. The only defence is the `<retrieved_context>` "data not instructions" wrapper at query time (`base.py:34-42`). The 100-character overlap catches only short phrases that straddle a boundary (`document_parsers.py:96`). | "Per-chunk scanning misses it; I only have delimiting at query time. I'd also scan the assembled context per query." |
| 4 | Poisoned doc tells the groundedness checker the answer is supported | **Not handled** | The verifier is general GPT-4o, with raw context pasted inline and **no delimiters** (`groundedness.py:42-60, 88-89`). **Verified:** a verifier-targeted note isn't flagged at ingestion. | "My checker is an instruction-following LLM reading attacker text, so it's injectable. I'd swap in a narrow NLI verifier that sees one claim and one chunk in a fixed format." |
| 5 | Poisoned source, so the answer is "grounded" in a lie | **Not handled** | No source trust or provenance ranking. Anonymous `/ingest` (`main.py:132`). Graph node properties are **last-writer-wins** (`writer.py:75-79`), so one upload can overwrite "P-101 design pressure". | "Groundedness isn't truth. I'd add uploader identity, provenance and trust-weighted ranking, and stop node properties being silently overwritten." |
| 6 | 20 near-duplicate copies to dominate retrieval | **Not handled** | Whole-file SHA-256 only (`document_parsers.py:45-51`). Reranker dedup is by `doc_id`, which differs per upload (`reranker.py:64-71`). **My committed store already holds 3–4 copies of five files.** | "SHA-256 only stops byte-identical files. My own demo store has the same file four times, so MinHash at chunk level plus per-uploader quotas is next." |
| 7 | Exfiltration via markdown image or link in the answer | **Partly (mostly by accident)** | Regex flags `![…](http` at ingestion (`injection_scanner.py:74`). The UI renders the answer as **plain text**, with no markdown renderer, so images never auto-load (`ChatInterface.tsx:136-138`, `frontend/package.json`). Plain links aren't flagged (verified), and there's no server-side output sanitisation. | "My UI doesn't render markdown, so image beacons don't fire, but that's luck, not policy. I'd sanitise output and allowlist link domains server-side." |
| 8 | Requesting unauthorised documents, including via graph hops | **Not handled** | No auth or ACL anywhere. `role_tag` exists but is never set or filtered (`ontology.py:51`). LLM-written Cypher reaches any node (`graph_search.py:46-70`). | "There's no access control today, and on the graph it would need checking at every hop, not just the start node. I have the role_tag field to hang it on." |
| 9 | PII the redactor misses | **Not handled (beyond display regex)** | **Verified misses:** unspaced Aadhaar, lowercase PAN, names, employee IDs, DOB, bank details; phone leaks a digit. Answer text is never redacted. OCR text from images isn't redacted. `Person` nodes are stored raw (`pii.py`, `base.py:104`). | "Redaction is a display-layer regex on citation snippets, so it misses names and unspaced Aadhaar and never touches the answer. Next is NER plus India-specific patterns before indexing." |
| 10 | Flooding the human review queue | **N/A today: there is no queue**; **not handled** for rate limits | No queue, no rate limits (`main.py`). Because the trigger is keywords on the question, an attacker **can't suppress** it, but every LOTO question escalates, which creates **banner fatigue**. | "There's no reviewer queue to flood yet; when I build one I'd use rule-based triggers, prioritisation and per-user rate limits so reviewers don't rubber-stamp." |
| 11 | PII leaking into audit logs | **Not handled** | Raw query (`audit_log.py:96`) and a raw 200-character chunk preview (`pipeline.py:121`, `audit_log.py:59`) are written unredacted. Not tamper-evident. | "Yes, my logs hold raw queries and chunk previews. I'd redact before logging, restrict access, and hash-chain entries with the SHA-256 I already use." |
| 12 | Injection steering an agent into a loop or runaway cost | **Partly** | The graph is a DAG with no cycles and no tools, so each query makes a bounded number of LLM calls (`supervisor.py:445-466`). But there are no LLM timeouts or `max_tokens` on the agents (`base.py:73-81`), and no rate limits or cost budgets. `/eval/run` and `/ingest` are unauthenticated cost sinks. Generated Cypher has no DB timeout. | "Loops can't happen, because the graph is acyclic and agents have no tools, but cost isn't bounded. I'd add timeouts, max_tokens, per-user budgets and auth on the expensive endpoints." |

**Summary line to say out loud:** "Of your twelve, I'd say I handle the loop case by design, I partly handle image-borne and split injections and markdown exfiltration, and I don't handle obfuscation, verifier injection, source poisoning, near-duplicates, access control, PII gaps or log PII. Here's the order I'd fix them: access control and read-only Cypher first, because those are blast radius; then detection quality."

---

## Appendix — short answers for other likely follow-ups

- **"Hybrid of what?"** "Vector search in ChromaDB plus LLM-generated Cypher over a Neo4j knowledge graph, fused by a weighted score. It's not the dense-plus-BM25 hybrid from your RAG post. I didn't add BM25, and I'd add it next for exact identifiers like P-101 or WO-2024-0312, where embeddings are weak. I'd also switch fusion to Reciprocal Rank Fusion, because my cosine and path-length scores aren't on the same scale." (`reranker.py:14-76`)
- **"When does the graph beat vector?"** The repo has no recorded example. **Don't invent one.** Say: "On relationship questions like 'what's connected to V-201'. My P&ID extraction gives CONNECTED_TO edges that vector search can't follow. I didn't log a head-to-head comparison, which is part of the eval I'd build." (`document_parsers.py:222-223`, `extractor.py:44`)
- **"How did you build the graph?"** Part 1 #12. Name both weaknesses yourself: wrong extractions become permanent facts (and here the latest upload overwrites properties), and there's no entity resolution beyond identical LLM-chosen IDs.
- **"How do you chunk spreadsheets and diagrams?"** Part 1 #11. Spreadsheets: generic 800-character windows, no repeated header, which is the next fix. Diagrams: one chunk of OCR text plus vision JSON.
- **"Tesseract and GPT-4 Vision, why both?"** "For image uploads I run both. OCR catches small printed labels; GPT-4o reads tags and connections. Scanned PDF pages get Tesseract only. There's no cost-based routing yet." (`document_parsers.py:171-274`)
- **"Why ChromaDB?"** Prototyping speed and an on-disk store. For production: multi-tenant metadata filters for ACLs, or the customer's own Databricks or Snowflake vector search.
- **"SHA-256 on files or chunks?"** Whole files. Admit it, and cite the 3–4 duplicate copies in your own demo store.
- **"Your agents share state, what if one is poisoned?"** "Today agents don't read each other's output; `prior_outputs` is always empty because they run once in parallel. So there's no agent-to-agent path. The shared path is the retrieved context, which every agent gets in full."
- **"Have you used garak, PyRIT, promptfoo?"** Nothing in this repo uses them. Answer honestly about your own experience.

> **One optional pre-interview action (your call, not done here):** the read-only Cypher issue is a one-line fix: open the session with `default_access_mode=neo4j.READ_ACCESS` in `graph_search.py:106`. If you change it before the interview, update the Q11 answer to "I found it and fixed it".
