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
    record_fingerprint,
    parse_document,
)
from backend.ingestion import dedup
from backend.shared.ontology import DOC_TYPES
from backend.guardrails.injection_scanner import scan_chunk, PATTERN_VERSION
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
    collection = get_chroma_collection()

    # 1. Fingerprint check — the vector store is the source of truth (each chunk
    # carries file_sha256), so a lost/reset cache can't cause re-ingestion.
    fp = fingerprint_file(file_path)
    already_stored = bool(collection.get(where={"file_sha256": fp}, limit=1)["ids"])
    if fp in fingerprint_cache or already_stored:
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
    #    and near-duplicate filtering (MinHash against every stored chunk).
    existing_sigs = [
        dedup.decode(m["minhash"])
        for m in collection.get(include=["metadatas"])["metadatas"]
        if m and m.get("minhash")
    ]
    near_duplicates = 0
    chunk_ids = []
    clean_chunks = []  # chunks with no injection signal at all — the only text the graph may see
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

        # Near-duplicate of a chunk already stored (or earlier in this doc)?
        signature = dedup.minhash(chunk)
        if dedup.is_near_duplicate(signature, existing_sigs, settings.NEAR_DUP_JACCARD):
            near_duplicates += 1
            continue
        existing_sigs.append(signature)

        # Build metadata — flag regex-matched (but LLM-cleared) chunks
        chunk_metadata = {
            "doc_id": doc_id,
            "doc_type": doc_type,
            "file_name": Path(file_path).name,
            "chunk_index": i,
            "total_chunks": len(chunks),
            "injection_flagged": scan_result["flagged"],
            "scan_version": PATTERN_VERSION,
            "file_sha256": fp,
            "minhash": dedup.encode(signature),
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
        if not scan_result["flagged"]:
            clean_chunks.append(chunk)

    if injection_blocked:
        console.print(f"  [red]✗ {injection_blocked} chunk(s) blocked as injection attempts[/red]")
    if near_duplicates:
        console.print(f"  [yellow]⏭ {near_duplicates} near-duplicate chunk(s) skipped[/yellow]")

    console.print(f"  → {len(chunk_ids)} chunks stored in ChromaDB")

    # 4. Two-pass extraction → Neo4j
    # Only scanned, fully clean chunks reach the graph extractor. Blocked chunks
    # and regex-flagged (even if LLM-cleared) chunks are excluded: a bad fact in
    # the graph is permanent and is reused across every future query.
    extractor = TwoPassExtractor()
    full_text = "\n\n".join(clean_chunks)[:12000]  # Limit for LLM context
    if full_text.strip():
        extracted = await extractor.extract(full_text, doc_id, doc_type)
    else:
        console.print("  [yellow]⚠ No clean text — skipping graph extraction[/yellow]")
        extracted = {"nodes": [], "edges": []}

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

    # 5. Update fingerprint cache — in memory and on disk immediately (atomic, merged)
    entry = {"doc_id": doc_id, "file_path": file_path, "ingested_at": extractor.extracted_at}
    fingerprint_cache[fp] = entry
    record_fingerprint(settings.DOC_FINGERPRINT_CACHE, fp, entry)

    return {
        "status": "success",
        "doc_id": doc_id,
        "chunks": len(chunks),
        "chunks_stored": len(chunk_ids),
        "near_duplicates": near_duplicates,
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
    # (fingerprints are persisted per document inside ingest_document)

    # Summary
    success = sum(1 for r in results if r["status"] == "success")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    errors = sum(1 for r in results if r["status"] == "error")
    console.print(f"\n[bold green]Done! ✓ {success} ingested, {skipped} skipped, {errors} errors[/bold green]")


if __name__ == "__main__":
    app()
