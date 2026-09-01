// API client for the Cerebra-CorpCortex backend
// Kavyansh: import these functions in your components

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface Citation {
  doc_id: string;
  title: string;
  doc_type: string;
  chunk_index: number;
  text_span: string;
  score: number;
  source: "vector" | "graph";
  extra_excerpts?: string[];
  extra_count?: number;
}

export interface GraphPathNode {
  node_id: string;
  node_type: string;
  label: string;
  edge_type?: string;
}

export interface QueryResponse {
  answer: string;
  supporting_detail: string;
  citation_note: string;
  citations: Citation[];
  confidence: number;
  confidence_label: "High" | "Medium" | "Low";
  retrieval_path: "vector" | "graph" | "hybrid";
  graph_path: GraphPathNode[];
  query_type: string;
  agent_used: string[];
  retrieval_strategy: string;
  latency_ms: number;
  // Guardrails fields
  groundedness_warning?: string[];
  escalation_notice?: string;
}

export interface IngestResponse {
  status: "success" | "skipped" | "error";
  doc_id?: string;
  chunks?: number;
  nodes?: number;
  edges?: number;
  message?: string;
}

export interface GraphStats {
  nodes: { type: string; count: number }[];
  total_edges: number;
}

export interface EvalReport {
  generated_at: string;
  num_questions: number;
  metrics: {
    answer_relevancy: number;
    faithfulness: number;
    context_recall: number;
    avg_latency_ms: number;
    avg_confidence: number;
  };
}

// ── Query ──────────────────────────────────────────────────────────────────

export async function queryKnowledgeBase(
  question: string,
  sessionId: string = "default"
): Promise<QueryResponse> {
  const res = await fetch(`${API_URL}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, session_id: sessionId }),
  });
  if (!res.ok) throw new Error(`Query failed: ${res.statusText}`);
  return res.json();
}

// ── Ingest ─────────────────────────────────────────────────────────────────

export async function ingestDocument(
  file: File,
  docType: string = "generic"
): Promise<IngestResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("doc_type", docType);

  const res = await fetch(`${API_URL}/ingest`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`Ingest failed: ${res.statusText}`);
  return res.json();
}

// ── Graph Stats ────────────────────────────────────────────────────────────

export async function getGraphStats(): Promise<GraphStats | null> {
  try {
    const res = await fetch(`${API_URL}/graph/stats`);
    if (!res.ok) throw new Error(`Stats failed: ${res.statusText}`);
    return res.json();
  } catch {
    return null;
  }
}

// ── Eval ───────────────────────────────────────────────────────────────────

export async function getEvalReport(): Promise<EvalReport> {
  const res = await fetch(`${API_URL}/eval/report`);
  if (!res.ok) throw new Error(`Eval report not found`);
  return res.json();
}

export async function triggerEval(): Promise<void> {
  await fetch(`${API_URL}/eval/run`, { method: "POST" });
}

// ── Health ─────────────────────────────────────────────────────────────────

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/health`);
    return res.ok;
  } catch {
    return false;
  }
}
