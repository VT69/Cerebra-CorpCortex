"""
FastAPI application — main entry point for the backend API.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import settings
from backend.agents.supervisor import run_query
from backend.ingestion.pipeline import ingest_document, load_fingerprint_cache, save_fingerprint_cache
from backend.shared.ontology import AgentResponse
from dataclasses import asdict
import shutil


# ─────────────────────────────────────────────────────────────────────────────
# Startup / Shutdown
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure data dirs exist
    os.makedirs(settings.DOC_UPLOAD_DIR, exist_ok=True)
    os.makedirs(settings.CHROMA_PERSIST_DIR, exist_ok=True)
    os.makedirs("./data/eval", exist_ok=True)
    yield


app = FastAPI(
    title="IndustrialIQ API",
    description="AI-powered Industrial Knowledge Intelligence Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str
    session_id: str = "default"


class QueryResponse(BaseModel):
    answer: str
    supporting_detail: str = ""
    citation_note: str = ""
    citations: list[dict]
    confidence: float
    confidence_label: str = "Low"
    retrieval_path: str = "vector"
    graph_path: list[dict]
    query_type: str
    agent_used: list[str]
    retrieval_strategy: str
    latency_ms: int
    # Guardrails fields
    groundedness_warning: list[str] = []
    escalation_notice: str = ""


class IngestResponse(BaseModel):
    status: str
    doc_id: str | None = None
    chunks: int = 0
    nodes: int = 0
    edges: int = 0
    message: str = ""


class QMSIncidentPayload(BaseModel):
    incident_id: str
    equipment_id: str
    description: str
    severity: str
    date: str
    reported_by: str = "System"


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "IndustrialIQ API"}


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    """
    Main query endpoint — runs the full supervisor pipeline.
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    try:
        response = await run_query(request.question)
        return QueryResponse(
            answer=response.answer,
            supporting_detail=getattr(response, 'supporting_detail', ''),
            citation_note=getattr(response, 'citation_note', ''),
            citations=response.citations,
            confidence=response.confidence,
            confidence_label=getattr(response, 'confidence_label', 'Low'),
            retrieval_path=getattr(response, 'retrieval_path', 'vector'),
            graph_path=response.graph_path,
            query_type=response.query_type,
            agent_used=response.agent_used,
            retrieval_strategy=response.retrieval_strategy,
            latency_ms=response.latency_ms,
            groundedness_warning=getattr(response, 'groundedness_warning', []),
            escalation_notice=getattr(response, 'escalation_notice', ''),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest", response_model=IngestResponse)
async def ingest(
    file: UploadFile = File(...),
    doc_type: str = Form("generic"),
):
    """
    Upload and ingest a document into the knowledge base.
    Supported: PDF, DOCX, XLSX, CSV, TXT, PNG/JPG (P&IDs), EML
    """
    # Save uploaded file
    upload_path = os.path.join(settings.DOC_UPLOAD_DIR, file.filename)
    with open(upload_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Run ingestion
    fp_cache = load_fingerprint_cache(settings.DOC_FINGERPRINT_CACHE)
    result = await ingest_document(upload_path, doc_type, fp_cache)
    save_fingerprint_cache(fp_cache, settings.DOC_FINGERPRINT_CACHE)

    if result["status"] == "skipped":
        return IngestResponse(status="skipped", message="Document already in knowledge base")
    elif result["status"] == "error":
        return IngestResponse(status="error", message=result.get("reason", "Unknown error"))
    else:
        return IngestResponse(
            status="success",
            doc_id=result["doc_id"],
            chunks=result["chunks"],
            nodes=result["nodes"],
            edges=result["edges"],
        )


@app.post("/webhook/qms/incident")
async def qms_webhook(payload: QMSIncidentPayload):
    """
    Direct QMS/ERP Webhook Integration.
    Bypasses OCR and injects a non-conformance/incident directly into the Knowledge Graph.
    Includes deduplication to prevent double-counting.
    """
    from backend.graph.writer import get_driver
    from datetime import datetime
    import json
    
    driver = await get_driver()
    try:
        async with driver.session() as session:
            # 1. Deduplication check
            check_res = await session.run(
                "MATCH (e:Event {incident_id: $iid}) RETURN e", 
                iid=payload.incident_id
            )
            if await check_res.single():
                return {"status": "skipped", "message": f"Incident {payload.incident_id} already exists in graph"}

            # 2. Insert Event and link to Equipment
            query = """
            MERGE (eq:Equipment {node_id: $eq_id})
            ON CREATE SET eq.label = $eq_id
            
            CREATE (ev:Event {
                node_id: $ev_id,
                incident_id: $iid,
                label: $desc,
                severity: $sev,
                date: $date,
                reported_by: $reporter
            })
            
            MERGE (ev)-[r:CAUSED_BY {
                confidence: 1.0, 
                extracted_by: 'QMS_Webhook', 
                extracted_at: $now
            }]->(eq)
            
            RETURN count(ev) as nodes, count(r) as edges
            """
            
            res = await session.run(query, 
                eq_id=payload.equipment_id,
                ev_id=f"evt_{payload.incident_id}",
                iid=payload.incident_id,
                desc=payload.description[:100],
                sev=payload.severity,
                date=payload.date,
                reporter=payload.reported_by,
                now=datetime.utcnow().isoformat()
            )
            record = await res.single()
            nodes = record["nodes"] if record else 0
            edges = record["edges"] if record else 0
            
            return {
                "status": "success", 
                "message": f"Injected incident {payload.incident_id} into Knowledge Graph",
                "nodes_added": nodes,
                "edges_added": edges
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await driver.close()


@app.get("/eval/report")
async def get_eval_report():
    """Return the latest eval report."""
    report_path = "./data/eval/latest_report.json"
    if not os.path.exists(report_path):
        raise HTTPException(status_code=404, detail="No eval report found. Run eval pipeline first.")
    import json
    with open(report_path) as f:
        return json.load(f)


@app.post("/eval/run")
async def trigger_eval():
    """Trigger the eval pipeline manually."""
    from backend.eval.eval_pipeline import run_eval
    import asyncio
    # Run in background
    asyncio.create_task(run_eval())
    return {"status": "started", "message": "Eval pipeline started. Check /eval/report for results."}


@app.get("/graph/stats")
async def graph_stats():
    """Return basic stats about the knowledge graph."""
    from backend.graph.writer import get_driver
    driver = None
    try:
        driver = await get_driver()
        async with driver.session() as session:
            result = await session.run("""
                MATCH (n)
                RETURN labels(n)[0] as type, count(n) as count
                ORDER BY count DESC
            """)
            records = await result.data()
            edge_result = await session.run("MATCH ()-[r]->() RETURN count(r) as total_edges")
            edge_data = await edge_result.data()
        return {
            "nodes": records,
            "total_edges": edge_data[0]["total_edges"] if edge_data else 0,
        }
    except Exception as e:
        print(f"[GraphStats] Neo4j unavailable: {e}")
        return {"nodes": [], "total_edges": 0, "status": "Graph database disconnected"}
    finally:
        if driver:
            await driver.close()
