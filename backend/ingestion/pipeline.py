"""
Main ingestion pipeline. Orchestrates:
1. Fingerprint check (skip if already processed)
2. Parse document (per-type parser)
3. Embed chunks → ChromaDB
4. Two-pass extraction → Neo4j graph
5. Update fingerprint cache

Vaibhav owns this file.

Usage:
  python -m backend.ingestion.pipeline --dir ./sample_docs
  python -m backend.ingestion.pipeline --file ./sample_docs/work_order.pdf --doc-type work_order
"""
import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Optional

import chromadb
import typer
from openai import AsyncOpenAI
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from backend.config import settings
from backend.graph.writer import GraphWriter, get_driver
from backend.ingestion.extractor import TwoPassExtractor
from backend.ingestion.parsers.document_parsers import (
    fingerprint_file,
    load_fingerprint_cache,
    save_fingerprint_cache,
    parse_document,
)
from backend.shared.ontology import DOC_TYPES
from backend.guardrails.injection_scanner import scan_chunk
from backend.guardrails.audit_log import log_injection_attempt, log_injection_flagged

app = typer.Typer()
console = Console()

# ─────────────────────────────────────────────────────────────────────────────
# ChromaDB Setup
# ─────────────────────────────────────────────────────────────────────────────

def get_chroma_collection():
    client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    return client.get_or_create_collection(
        name=settings.CHROMA_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


async def embed_text(text: str) -> list[float]:
    """Get embedding from OpenAI."""
    oai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    response = await oai.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=text[:8191],  # Token limit
    )
    return response.data[0].embedding


# ─────────────────────────────────────────────────────────────────────────────
# Core ingestion function
# ─────────────────────────────────────────────────────────────────────────────

async def ingest_document(
    file_path: str,
    doc_type: str = "generic",
    fingerprint_cache: dict = None,
) -> dict:
    """
    Ingest a single document through the full pipeline.
    Returns summary of what was written.
    """
    fingerprint_cache = fingerprint_cache or {}

    # 1. Fingerprint check
    fp = fingerprint_file(file_path)
    if fp in fingerprint_cache:
        console.print(f"[yellow]⏭  Skipping (already processed):[/yellow] {Path(file_path).name}")
        return {"status": "skipped", "reason": "already_processed"}

    console.print(f"[cyan]📄 Processing:[/cyan] {Path(file_path).name}")
    doc_id = str(uuid.uuid4())

    # 2. Parse
    parsed = parse_document(file_path, doc_type)

    # None means extraction failed (e.g. P&ID vision error) — do NOT ingest
    if parsed is None:
        console.print(f"[red]  ✗ Extraction failed — document will NOT be ingested[/red]")
        return {"status": "error", "reason": "extraction_failed"}

    chunks = parsed["chunks"]
    if not chunks:
        console.print(f"[red]  ✗ No content extracted[/red]")
        return {"status": "error", "reason": "no_content"}

    console.print(f"  → {len(chunks)} chunks extracted")

    # 3. Embed and store in ChromaDB with injection scanning (Section 2)
    collection = get_chroma_collection()
    chunk_ids = []
    injection_blocked = 0
    for i, chunk in enumerate(chunks):
        chunk_id = f"{doc_id}_chunk_{i}"

        # Section 2: Scan for prompt injection before embedding
        scan_result = await scan_chunk(chunk)

        if scan_result["is_injection"]:
            # LLM confirmed injection — block this chunk entirely
            log_injection_attempt(
                chunk_id=chunk_id,
                doc_id=doc_id,
                file_name=Path(file_path).name,
                text_preview=chunk[:200],
                matched_patterns=scan_result["matched_patterns"],
                llm_reasoning=scan_result["reasoning"],
            )
            console.print(f"  [red]⚠ Chunk {i} BLOCKED — injection attempt detected[/red]")
            injection_blocked += 1
            continue  # Skip embedding this chunk

        # Build metadata — flag regex-matched (but LLM-cleared) chunks
        chunk_metadata = {
            "doc_id": doc_id,
            "doc_type": doc_type,
            "file_name": Path(file_path).name,
            "chunk_index": i,
            "total_chunks": len(chunks),
            "injection_flagged": scan_result["flagged"],
        }

        if scan_result["flagged"] and not scan_result["is_injection"]:
            # Regex-flagged but LLM says it's legitimate — tag and ingest
            log_injection_flagged(
                chunk_id=chunk_id,
                doc_id=doc_id,
                file_name=Path(file_path).name,
                matched_patterns=scan_result["matched_patterns"],
            )
            console.print(f"  [yellow]⚠ Chunk {i} flagged (regex) but cleared by LLM — tagged in metadata[/yellow]")

        embedding = await embed_text(chunk)
        collection.upsert(
            ids=[chunk_id],
            embeddings=[embedding],
            documents=[chunk],
            metadatas=[chunk_metadata],
        )
        chunk_ids.append(chunk_id)

    if injection_blocked:
        console.print(f"  [red]✗ {injection_blocked} chunk(s) blocked as injection attempts[/red]")

    console.print(f"  → {len(chunk_ids)} chunks stored in ChromaDB")

    # 4. Two-pass extraction → Neo4j
    extractor = TwoPassExtractor()
    # Extract from full text (not individual chunks) for better context
    full_text = parsed["text"][:12000]  # Limit for LLM context
    extracted = await extractor.extract(full_text, doc_id, doc_type)

    nodes_written = 0
    edges_written = 0

    if extracted["nodes"] or extracted["edges"]:
        driver = await get_driver()
        writer = GraphWriter(driver)
        await writer.initialize_schema()

        # Write Document node first
        from backend.shared.ontology import Provenance
        from datetime import datetime, timezone
        doc_prov = Provenance(
            source_doc_id=doc_id,
            confidence=1.0,
            extraction_pass_id=extractor.pass_id,
            extracted_at=extractor.extracted_at,
            extracted_by="ingestion-pipeline",
            verified=True,
        )
        await writer.upsert_node("Document", doc_id, {
            "title": Path(file_path).name,
            "doc_type": doc_type,
            "file_path": file_path,
            "fingerprint": fp,
            "chunk_count": len(chunks),
        }, doc_prov)

        # Write extracted nodes
        for item in extracted["nodes"]:
            node = item["node"]
            prov = item["provenance"]
            result = await writer.upsert_node(
                node["type"], node["id"], node["properties"], prov
            )
            if result:
                nodes_written += 1

        # Write extracted edges
        for item in extracted["edges"]:
            edge = item["edge"]
            prov = item["provenance"]
            committed = await writer.upsert_edge(
                edge["from_id"], edge["from_type"],
                edge["edge_type"],
                edge["to_id"], edge["to_type"],
                prov,
            )
            if committed:
                edges_written += 1
            else:
                console.print(f"  [yellow]⚠ Edge skipped or failed: {edge['from_id']} -[{edge['edge_type']}]-> {edge['to_id']}[/yellow]")

        await driver.close()

    console.print(f"  → [green]{nodes_written} nodes[/green], [green]{edges_written} edges[/green] written to graph")

    # 5. Update fingerprint cache
    fingerprint_cache[fp] = {
        "doc_id": doc_id,
        "file_path": file_path,
        "ingested_at": extractor.extracted_at,
    }

    return {
        "status": "success",
        "doc_id": doc_id,
        "chunks": len(chunks),
        "nodes": nodes_written,
        "edges": edges_written,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

EXTENSION_TO_DOCTYPE = {
    ".pdf": "generic",
    ".xlsx": "spreadsheet",
    ".xls": "spreadsheet",
    ".csv": "spreadsheet",
    ".txt": "generic",
    ".eml": "email",
    ".msg": "email",
    ".docx": "manual",
    ".png": "pid",
    ".jpg": "pid",
    ".tif": "pid",
}


@app.command()
def run(
    directory: Optional[str] = typer.Option(None, "--dir", help="Directory of documents to ingest"),
    file: Optional[str] = typer.Option(None, "--file", help="Single file to ingest"),
    doc_type: str = typer.Option("generic", "--doc-type", help="Document type hint"),
):
    """Run the ingestion pipeline on a directory or single file."""
    cache_path = settings.DOC_FINGERPRINT_CACHE
    fingerprint_cache = load_fingerprint_cache(cache_path)

    files_to_process = []
    if directory:
        for f in Path(directory).rglob("*"):
            if f.is_file():
                dt = EXTENSION_TO_DOCTYPE.get(f.suffix.lower(), "generic")
                files_to_process.append((str(f), dt))
    elif file:
        files_to_process.append((file, doc_type))
    else:
        console.print("[red]Provide --dir or --file[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]IndustrialIQ Ingestion Pipeline[/bold]")
    console.print(f"Processing {len(files_to_process)} file(s)...\n")

    results = []
    for fp, dt in files_to_process:
        result = asyncio.run(ingest_document(fp, dt, fingerprint_cache))
        results.append(result)

    save_fingerprint_cache(fingerprint_cache, cache_path)

    # Summary
    success = sum(1 for r in results if r["status"] == "success")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    errors = sum(1 for r in results if r["status"] == "error")
    console.print(f"\n[bold green]Done! ✓ {success} ingested, {skipped} skipped, {errors} errors[/bold green]")


if __name__ == "__main__":
    app()
