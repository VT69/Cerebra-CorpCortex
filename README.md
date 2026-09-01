# Cerebra-CorpCortex — The Enterprise AI Brain

The custom AI brain for your enterprise that seamlessly connects siloed documents into an interactive knowledge base. 

Cerebra-CorpCortex transforms static enterprise data (compliance manuals, operational logs, technical diagrams, and reports) into an interactive, multi-modal knowledge graph[cite: 5, 6]. It enables employees, auditors, and operations teams to instantly retrieve insights, perform root cause analysis, and verify compliance through natu0ral language.
////---

## 🚀 The Problem & Solution

**The Problem:** Modern enterprises generate vast amounts of unstructured and semi-structured data. Currently, when a critical process fails or an audit is required, employees spend hours sifting through disconnected PDFs, spreadsheets, and legacy databases. This leads to prolonged downtime, compliance risks, and the loss of institutional knowledge when experienced personnel leave.

**The Solution:** Cerebra-CorpCortex is an AI-powered, multi-modal knowledge intelligence platform. By unifying semantic vector search with graph-based relationship traversal, it allows users to ask natural language questions and receive accurate, highly-confident, and fully-cited answers based exclusively on their company's internal data.

---

## ✨ Key Features

- **Multi-Modal Document Ingestion:** Seamlessly processes PDFs, DOCX, XLSX, TXT, and raw images (like complex workflow or engineering diagrams).
- **Vision & OCR Engine:** Uses Tesseract OCR and GPT-4 Vision to extract text and spatial relationships from complex diagrams.
- **Knowledge Graph Extraction:** Automatically identifies enterprise entities (Departments, Parameters, Events, Regulations) and relationships (CAUSED_BY, DOCUMENTED_IN) and stores them in Neo4j.
- **Hybrid Retrieval System:** Combines ChromaDB (semantic vector search) with Neo4j (graph traversal) and a weighted reranker to ensure no context is missed.
- **Multi-Agent Orchestration:** Uses a LangGraph supervisor to dispatch queries to specialized AI agents (e.g., Operations, Compliance, Lessons Learned) in parallel.
- **Traceability & Citations:** Every fact is backed by a specific source document and confidence score, ensuring hallucination-free enterprise reliability.

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
```

---

## 🛠️ Local Setup

Follow these steps to run the platform locally on your machine.

### 1. Prerequisites
- Python 3.11+
- Node.js 18+
- [Neo4j AuraDB Free Account](https://neo4j.com/cloud/aura/) (or local Neo4j desktop)
- OpenAI API Key

### 2. Configure Environment Variables
Copy the example config and fill in your keys:

```bash
cp .env.example .env
```
Inside `.env`, provide your:
- `OPENAI_API_KEY`
- `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`

*(Optional) If you don't have Neo4j, the app will gracefully fall back to vector-only search.*

### 3. Start the Backend
```bash
python -m venv .venv
# Activate venv:
# Windows: .venv\Scripts\activate
# Mac/Linux: source .venv/bin/activate

pip install -r requirements.txt

# Start the API server
uvicorn backend.api.main:app --reload --port 8000
```
*API docs will be available at http://localhost:8000/docs.*

### 4. Start the Frontend
In a new terminal:
```bash
cd frontend
npm install
npm run dev
```
*The UI will be available at http://localhost:3000.*

---

## 🔍 Try These Demo Queries!

Once the system is running, try asking these questions to see the multi-agent system in action (assuming default enterprise/industrial sample data is loaded):

- **Operations & RCA:** "What is the MTBF for Pump P-101 and what caused its last failure?"
- **Compliance & Safety:** "Are we compliant with current regulations for our gas detectors?"
- **Multi-Hop Graph Search:** "Show me the maintenance history for any equipment connected to Valve V-201."
- **Image Vision:** "What are the operating parameters shown in the provided system diagram?"

---

## 💻 Technology Stack

- **Orchestration:** LangGraph, LangChain
- **Backend Framework:** FastAPI (Python)
- **Frontend Framework:** Next.js (React), TailwindCSS
- **Vector Database:** ChromaDB
- **Graph Database:** Neo4j (AuraDB Free)
- **LLM / Vision:** OpenAI GPT-4o, GPT-4 Vision
- **OCR Engine:** pytesseract, OpenCV, pdf2image
- **Evaluation:** Ragas, Langfuse