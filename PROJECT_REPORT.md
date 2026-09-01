```
```

# NexusRAG: AI-Powered Industrial Knowledge Intelligence Platform

## 1. Problem Statement

Industrial plants and manufacturing facilities generate vast amounts of unstructured and semi-structured data: P&IDs (Piping & Instrumentation Diagrams), maintenance logs, safety inspection reports, and compliance manuals (like OSHA or OISD).

Currently, when a piece of equipment fails or a safety audit is required, engineers spend hours sifting through disconnected PDFs, spreadsheets, and legacy databases to find relevant context. This manual process leads to:

- Prolonged downtime during root cause analysis (RCA).
- Increased risk of safety or compliance violations.
- Loss of institutional knowledge ("lessons learned") when experienced operators leave.

## 2. Solution: NexusRAG

NexxusRAG is an AI-powered, multi-modal knowledge intelligence platform that ingests these disparate documents and transforms them into an interactive Knowledge Graph.

By unifying semantic vector search with graph-based relationship traversal, IndustrialIQ allows users to ask natural language questions (e.g., *"What caused the last failure of Pump P-101 and what are the OSHA compliance requirements for it?"*) and receive accurate, highly-confident, and fully-cited answers.

## 3. Key Features

- **Multi-Modal Document Ingestion**: Seamlessly processes PDFs, DOCX, XLSX, TXT, and raw images (P&IDs).
- **Vision & OCR Engine**: Uses Tesseract OCR and GPT-4 Vision to extract text and spatial relationships from complex engineering diagrams.
- **Knowledge Graph Extraction**: Automatically identifies entities (Equipment, Parameters, Events, Regulations) and relationships (CAUSED_BY, DOCUMENTED_IN) and stores them in Neo4j.
- **Hybrid Retrieval System**: Combines ChromaDB (semantic vector search) with Neo4j (graph traversal) and a weighted reranker to ensure no context is missed.
- **Multi-Agent Orchestration**: Uses a LangGraph supervisor to dispatch queries to specialized AI agents (Maintenance, Compliance, Lessons Learned) in parallel.
- **Traceability & Citations**: Every fact is backed by a specific source document and confidence score, ensuring hallucination-free enterprise reliability.

## 4. Architecture

### The Retrieval & Agent Flow

1. **Query Classifier**: Determines if a query is a single-fact lookup, a multi-hop reasoning task, or small talk.
2. **Hybrid Retrieval**:
   - *Vector Path*: Retrieves semantically similar document chunks from ChromaDB.
   - *Graph Path*: If the query requires complex reasoning (e.g., "Find all equipment connected to X that failed last month"), it translates the query to Cypher and traverses Neo4j.
3. **Supervisor Dispatch**: The LangGraph supervisor sends the context to specialized agents.
4. **Specialist Agents**:
   - **Copilot**: General Q&A and summarization.
   - **Maintenance Agent**: Focuses on MTBF, RCAs, and work orders.
   - **Compliance Agent**: Checks against OISD/OSHA/Factory Act standards.
   - **Lessons Learned Agent**: Identifies recurring failure patterns.
5. **Synthesis Engine**: Merges outputs, deduplicates citations, calculates final confidence, and delivers the response.

## 5. Technology Stack

- **Orchestration**: LangGraph, LangChain
- **Backend Framework**: FastAPI (Python)
- **Frontend Framework**: Next.js (React), TailwindCSS
- **Vector Database**: ChromaDB
- **Graph Database**: Neo4j (AuraDB Free)
- **LLM / Vision**: OpenAI GPT-4o, GPT-4 Vision
- **OCR Engine**: pytesseract, OpenCV, pdf2image
- **Evaluation**: Ragas, Langfuse

## 6. How to Test (For Judges)

The project is configured for one-click deployment:

- **Frontend**: Deployable to Vercel.
- **Backend**: Deployable to Render using the provided `Dockerfile` and `render.yaml`.
- **Pre-loaded Data**: The repository includes a `data/chroma` folder pre-ingested with sample industrial documents, allowing judges to test the Q&A engine instantly without waiting for a lengthy ingestion process.

Try asking: *"What is the MTBF for Pump P-101 and what caused its last failure?"*
