# Cerebra-CorpCortex — The Enterprise AI Brain

The custom AI brain for your enterprise that seamlessly connects siloed documents into an interactive knowledge base. 

Cerebra-CorpCortex transforms static enterprise data (compliance manuals, operational logs, technical diagrams, and reports) into an interactive, multi-modal knowledge graph[cite: 5, 6]. It enables employees, auditors, and operations teams to instantly retrieve insights, perform root cause analysis, and verify compliance through natural language.

---

## 🚀 The Problem & Solution

**The Problem:** Modern enterprises generate vast amounts of unstructured and semi-structured data. Currently, when a critical process fails or an audit is required, employees spend hours sifting through disconnected PDFs, spreadsheets, and legacy databases. This leads to prolonged downtime, compliance risks, and the loss of institutional knowledge when experienced personnel leave.

**The Solution:** Cerebra-CorpCortex is an AI-powered, multi-modal knowledge intelligence platform. By unifying semantic vector search with graph-based relationship traversal, it allows users to ask natural language questions and receive accurate, highly-confident, and fully-cited answers based exclusively on their company's internal data.

---

## ✨ Key Features

- **Multi-Modal Document Ingestion:** Seamlessly processes PDFs, DOCX, XLSX, TXT, and raw images (like complex workflow or engineering diagrams).
- **Vision & OCR Engine:** Uses Tesseract OCR and GPT-4 Vision to extract text and spatial relationships from complex diagrams.
- **Knowledge Graph Extraction:** Automatically identifies enterprise entities (Departments, Parameters, Events, Regulations) and relationships (CAUSED_BY, DOCUMENTED_IN) and stores them in Neo4j.
- **Hybrid Retrieval System:** Combines ChromaDB (semantic vector search) with Neo4j (graph traversal) and a weighted reranker to ensure no context is missed[cite: 5].
- **Multi-Agent Orchestration:** Uses a LangGraph supervisor to dispatch queries to specialized AI agents (e.g., Operations, Compliance, Lessons Learned) in parallel[cite: 5].
- **Traceability & Citations:** Every fact is backed by a specific source document and confidence score, ensuring hallucination-free enterprise reliability[cite: 5].

---

## 🏗️ Architecture

```text
User Query
    │
    ▼
FastAPI Gateway
    │
    ▼
LangGraph Supervisor 
    │
    ├─ 1. Query Classifier (single-fact / multi-hop / aggregation)
    │
    ├─ 2. Hybrid Retrieval
    │       ├── ChromaDB Vector Search (Semantic)
    │       └── Neo4j Graph Traversal (Relationships)
    │               └─ Weighted Reranker
    │
    ├─ 3. Specialist Agents (Parallel)
    │       ├── CopilotAgent (General Q&A)
    │       ├── MaintenanceAgent (Operations, RCAs, work orders)
    │       ├── ComplianceAgent (Internal Policies, OSHA, Industry Standards)
    │       └── LessonsLearnedAgent (Historical incident patterns)
    │
    └─ 4. Synthesis Engine ── Final answer + citations + confidence